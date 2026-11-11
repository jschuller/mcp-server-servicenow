"""Credential-type system property values are never returned.

``sys_properties.value`` is a string column: whether a row's value is a
credential depends on the row's ``type`` (``password``, ``password2``). The
Table API returns those values to an identity that can read the table, with
every ``sysparm_display_value``. Every tool that returns rows builds a
``Guard`` for its request and applies it to the rows before they leave:

- a ``sys_properties`` row: ``value`` is replaced with ``REDACTED`` when the
  type is credential-type, and also when the type is missing (an ACL can hide
  it), empty or not one of the known plain types, so an unreadable type fails
  closed;
- a dot-walk to a property from another table (``property.value``): the same,
  with the type read from ``<reference>.type`` and the table from
  ``<reference>.sys_class_name``. Some properties have neither set, so a
  walked value is returned only when the record's type is a known plain one,
  its class names another table, or it has neither field at all;
- the instance's own copies of a property value: the old and new values of an
  audit or history row for ``sys_properties.value`` (the row carries no type,
  so all of them), read from the table or through a dot-walk to it, and any
  field that holds a ``<sys_properties>`` element, such as an update set
  payload: that field is withheld whole, whatever the record's type says,
  because no reading of the markup short of a parser can be trusted.

Field names reach this module already checked (``middleware/policy.py``):
letters, digits and underscores, joined by single dots. A name is judged by
every segment, not by its last: ``value.zz`` is ``value``, and
``property.value.zz`` is a dot-walk to ``property.value``, whatever the
instance makes of the rest.

The type must be the stored one. ``fields=`` gets the helper fields it lacks
(dropped again from the rows), and ``display_value="true"`` is asked of the
instance as ``"all"`` and reduced to the display form here, since a display
label (``true | false`` for ``boolean``) is not the stored type. Names are
compared generously when deciding what to withhold (any case, any
whitespace) and exactly when deciding whether a helper is already asked for,
so no spelling of ``fields=`` leaves the type out or a value in.

An empty value stays empty: whether a property is set is not a secret, and
the marker has one fixed length. The Stats API returns values without their
row, so ``check_aggregate`` refuses the fields a row would have withheld.

Withheld is not "impossible to infer": a query that filters on ``value``
still shows which rows match. Nothing here logs or raises a value.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from servicenow_mcp.middleware.policy import PolicyError, searches_value

PROPERTY_TABLE = "sys_properties"
REDACTED = "[redacted: system property value withheld as credential-type]"
# The property types whose value is an ordinary one. Any other type is
# withheld: password and password2, and whatever this list doesn't know.
_PLAIN_TYPES = frozenset(
    {
        "boolean",
        "choicelist",
        "color",
        "date_format",
        "image",
        "integer",
        "short_string",
        "string",
        "time_format",
        "timezone",
        "uploaded_image",
    }
)

# Tables whose rows copy a field's old and new values: the field that names
# the changed table, the one that names the changed field, and the copies.
_Copy = Tuple[str, str, Tuple[str, ...]]
_COPIES: Dict[str, _Copy] = {
    "sys_audit": ("tablename", "fieldname", ("oldvalue", "newvalue")),
    "sys_history_line": (
        "set.table",
        "field",
        ("old", "old_value", "new", "new_value"),
    ),
}
# The same, by the name of the copy: what a dot-walk to such a row asks for.
_COPY_OF: Dict[str, _Copy] = {
    name: copy for copy in _COPIES.values() for name in copy[2]
}
# A property's record XML (an update set or version payload, a deleted
# record) has a <sys_properties ...> element, in any case, with or without
# attributes or a namespace prefix. The "<" may be plain, an XML entity
# (&lt;, &#60;, &#x3c;) or a JSON escape (\u003c): one level of escaping and
# no other. Not <sys_properties_category>.
_XML_RECORD_RE = re.compile(
    r"(?:<|&lt;|&#0*60;|&#x0*3c;|\\u003c)(?:[\w.\-]+:)?sys_properties(?!\w)", re.I
)
# A key of a write to sys_properties: a plain column name and nothing else.
_COLUMN_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
# The instance trims ASCII whitespace and control characters (<= U+0020)
# around a field name, as Java's trim() does, and nothing else.
_TRIM = "".join(chr(code) for code in range(0x21))
# Property names and sys_ids only: a name is instance data, so nothing that
# could read as a sentence is repeated in a warning.
_LABEL_RE = re.compile(r"[A-Za-z0-9_.\-]{1,100}")
_MAX_LABELS = 10


def _name(text: Any) -> str:
    """A table or field name for comparison: trimmed and lowercase."""
    return text.strip().lower() if isinstance(text, str) else ""


def _names(fields: Optional[str]) -> List[str]:
    return [_name(part) for part in (fields or "").split(",") if part.strip()]


def _sent(fields: Optional[str]) -> List[str]:
    """The field names of ``fields=`` exactly as the instance reads them."""
    parts = [part.strip(_TRIM) for part in (fields or "").split(",")]
    return [part for part in parts if part]


def _watched(name: str) -> List[Tuple[str, str]]:
    """Each place where a field name passes through a watched field, as
    (the dot-walk that leads there, with its dot, or "" for a field of the
    table itself; the watched field).

    ``property.value`` and ``property.value.zz`` both give
    ``("property.", "value")``; ``value.value`` gives ``("", "value")`` and
    ``("value.", "value")``.
    """
    segments = name.split(".")
    return [
        (".".join(segments[:index]) + "." if index else "", segment)
        for index, segment in enumerate(segments)
        if segment == "value" or segment in _COPY_OF
    ]


def _by_name(row: Dict[str, Any]) -> Dict[str, List[str]]:
    """The row's keys under their compared name: an instance that matches
    names loosely can return two spellings of one field."""
    keys: Dict[str, List[str]] = {}
    for key in row:
        keys.setdefault(_name(key), []).append(key)
    return keys


def _stored(value: Any) -> Optional[str]:
    """A field's stored value, trimmed and case-folded, or None.

    A field arrives as a string, or as an object with ``value`` (a reference,
    or any field with ``display_value="all"``). None means it can't be read:
    the value is null or of another type.
    """
    if isinstance(value, dict):
        value = value.get("value")
    return value.strip().casefold() if isinstance(value, str) else None


def _is_credential_type(stored: Optional[str]) -> Optional[bool]:
    """Whether a stored property type is credential-type; None if unknown.

    ``password`` and ``password2``, and any later type named the same way.
    A missing or empty type is unknown, not "string", and so is a type that
    is not one of the known plain ones.
    """
    if stored and stored.startswith("password"):
        return True
    return False if stored in _PLAIN_TYPES else None


def _credential(row: Dict[str, Any], keys: Sequence[str]) -> Optional[bool]:
    """Whether the type under ``keys`` is credential-type: True if any
    spelling says so, None if none came back or one can't be read."""
    kinds = [_is_credential_type(_stored(row[key])) for key in keys]
    if True in kinds:
        return True
    return None if not kinds or None in kinds else False


def _is(row: Dict[str, Any], keys: Sequence[str], expected: str) -> bool:
    """Whether a field holds ``expected``, or can't be read (fail closed)."""
    stored = [_stored(row[key]) for key in keys]
    return not stored or any(not text or text == expected for text in stored)


def _empty(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_empty(part) for part in value.values())
    return value is None or value == ""


def _withhold(row: Dict[str, Any], key: str) -> bool:
    """Replace a non-empty field with the marker, keeping its shape."""
    value = row[key]
    if _empty(value):
        return False
    row[key] = (
        {part: REDACTED for part in value} if isinstance(value, dict) else REDACTED
    )
    return True


def _holds_property_xml(text: str) -> bool:
    """Whether a string holds a system property's record XML.

    Any ``<sys_properties>`` element counts, whatever type it states: the
    markup is not parsed, and text inside a record (a description in CDATA)
    can imitate the element that would say the type is a plain one.
    """
    return bool(_XML_RECORD_RE.search(text))


def scrub(value: Any) -> Tuple[Any, int]:
    """``value`` with every string that holds a property's record XML
    replaced by the marker, and how many were replaced. Lists and objects
    are changed in place."""
    if isinstance(value, str):
        return (REDACTED, 1) if _holds_property_xml(value) else (value, 0)
    count = 0
    if isinstance(value, dict):
        for key in value:
            value[key], found = scrub(value[key])
            count += found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index], found = scrub(item)
            count += found
    return value, count


def _display_only(value: Any) -> Any:
    """One field of a ``display_value="all"`` row as ``"true"`` returns it:
    the display string, or ``{display_value, link}`` for a reference."""
    if not isinstance(value, dict) or "display_value" not in value:
        return value
    if "link" in value:
        return {"display_value": value["display_value"], "link": value["link"]}
    return value["display_value"]


def _label(row: Dict[str, Any], keys: Dict[str, List[str]]) -> Optional[str]:
    """The property's name, else its sys_id, if either is safe to repeat."""
    for name in ("name", "sys_id"):
        for key in keys.get(name, []):
            value = row[key]
            if isinstance(value, dict):
                value = value.get("value")
            if isinstance(value, str) and _LABEL_RE.fullmatch(value):
                return value
    return None


def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _labelled(labels: List[Optional[str]]) -> str:
    known = [label for label in labels if label]
    if not known:
        return ""
    more = len(labels) - min(len(known), _MAX_LABELS)
    return f" ({', '.join(known[:_MAX_LABELS])}{f' and {more} more' if more else ''})"


class _Withheld:
    """What one call withheld, and the sentence that says so."""

    def __init__(self) -> None:
        self.credential: List[Optional[str]] = []
        self.unknown: List[Optional[str]] = []
        self.walked: Dict[str, int] = {}
        self.copies = 0
        self.xml = 0

    def warning(self, value_filter: bool) -> Optional[str]:
        parts: List[str] = []
        if self.credential:
            parts.append(
                "Withheld the value of "
                + _count(len(self.credential), "system property", "system properties")
                + _labelled(self.credential)
                + ": the type is password or password2, and this server never "
                "returns a credential-type property's value. A withheld value is "
                "set, not empty."
            )
        if self.unknown:
            parts.append(
                "Withheld the value of "
                + _count(len(self.unknown), "system property", "system properties")
                + _labelled(self.unknown)
                + " whose type is empty, not a known plain type, or did not come "
                "back (an ACL can hide it): without a type known to be plain the "
                "value is treated as credential-type."
            )
        for field, rows in self.walked.items():
            parts.append(
                f"Withheld {field} in {_count(rows, 'row', 'rows')}: the dot-walk "
                "reaches a record whose type is password or password2 (a "
                "credential-type system property), or one that may be a system "
                "property and has no type known to be plain."
            )
        if self.copies:
            parts.append(
                "Withheld the old and new values in "
                + _count(self.copies, "row that records", "rows that record")
                + " a change to a system property's value: the row doesn't carry "
                "the property's type, so each is treated as credential-type."
            )
        if self.xml:
            parts.append(
                "Withheld "
                + _count(self.xml, "field that holds", "fields that hold")
                + " a system property's record XML (an update set payload, for "
                "example): such a field is withheld whole, whatever the "
                "property's type, since it carries the value. "
                "list_update_set_changes still lists what changed."
            )
        if value_filter and (self.credential or self.unknown):
            parts.append(
                "query= filters on value or searches text, and matched a withheld "
                "row, so the match itself says something about that value: "
                "withheld is not the same as impossible to infer. Don't use such "
                "filters to work out a credential."
            )
        return " ".join(parts) or None


class Guard:
    """Withholds credential-type property values from one request's rows.

    Send ``fields`` as ``sysparm_fields`` and ``display_value`` as
    ``sysparm_display_value``: both may differ from what the caller asked
    for. Then call ``apply`` on the rows, which restores the caller's shape.
    """

    def __init__(
        self,
        table_name: str,
        fields: Optional[str] = None,
        display_value: str = "false",
    ) -> None:
        self.table = _name(table_name)
        sent = _sent(fields)
        helpers: List[str] = []
        if self.table == PROPERTY_TABLE:
            helpers.append("type")
        if self.table in _COPIES:
            helpers.extend(_COPIES[self.table][:2])
        for name in _names(fields):
            for reference, field in _watched(name):
                if not reference:
                    continue
                if field == "value":
                    helpers += [reference + "sys_class_name", reference + "type"]
                else:
                    table_field, field_field, _ = _COPY_OF[field]
                    helpers += [reference + table_field, reference + field_field]
        # A helper is left out only if this exact name is already asked for:
        # another spelling of it (TYPE) may be a field the instance drops.
        self.added = [
            name for name in dict.fromkeys(helpers) if sent and name not in sent
        ]
        self.fields = (
            ",".join([(fields or "").strip(_TRIM), *self.added])
            if self.added
            else fields
        )
        # A display label is not the stored type: read both, return one.
        self._reduce = bool(helpers) and display_value == "true"
        self.display_value = "all" if self._reduce else display_value

    def apply(self, rows: Sequence[Any], query: Optional[str] = None) -> Optional[str]:
        """Withhold in place, drop the helper fields, and return the warning
        for the result, or None when nothing was withheld. ``query`` is the
        caller's encoded query, for the note on value filters."""
        withheld = _Withheld()
        for row in rows:
            if not isinstance(row, dict):
                continue
            self._check(row, withheld)
            for name in self.added:
                row.pop(name, None)
            if self._reduce:
                for key in row:
                    row[key] = _display_only(row[key])
        return withheld.warning(self.table == PROPERTY_TABLE and searches_value(query))

    def _check(self, row: Dict[str, Any], withheld: _Withheld) -> None:
        keys = _by_name(row)
        found: Dict[str, Optional[str]] = {}
        for name, spellings in keys.items():
            for reference, field in _watched(name):
                reason = self._reason(row, keys, reference, field)
                if reason and any([_withhold(row, key) for key in spellings]):
                    # One entry per row and reason: two fields of one
                    # property are one withheld property.
                    found[reason] = reference + field
        if "credential" in found or "unknown" in found:
            group = withheld.unknown if "unknown" in found else withheld.credential
            group.append(_label(row, keys))
        if "walk" in found:
            walked = str(found["walk"])
            withheld.walked[walked] = withheld.walked.get(walked, 0) + 1
        withheld.copies += "copy" in found
        for key in row:
            row[key], scrubbed = scrub(row[key])
            withheld.xml += bool(scrubbed)

    def _reason(
        self,
        row: Dict[str, Any],
        keys: Dict[str, List[str]],
        reference: str,
        field: str,
    ) -> Optional[str]:
        """Why a field that is, or passes through, ``reference + field`` is
        withheld in this row, or None if it is not."""
        if field == "value" and not reference:
            if self.table != PROPERTY_TABLE:
                return None
            credential = _credential(row, keys.get("type", []))
            if credential is False:
                return None
            return "unknown" if credential is None else "credential"
        if field == "value":
            return "walk" if self._reaches_credential(row, keys, reference) else None
        if not reference:
            copy = _COPIES.get(self.table)
            if copy is None or field not in copy[2]:
                return None
        else:
            copy = _COPY_OF[field]
        table_keys = keys.get(reference + copy[0], [])
        field_keys = keys.get(reference + copy[1], [])
        # A walked record with neither of these fields is no audit row. A
        # row of the table itself that doesn't say what it records fails
        # closed.
        if reference and not (table_keys or field_keys):
            return None
        recorded = _is(row, table_keys, PROPERTY_TABLE) and _is(
            row, field_keys, "value"
        )
        return "copy" if recorded else None

    @staticmethod
    def _reaches_credential(
        row: Dict[str, Any], keys: Dict[str, List[str]], reference: str
    ) -> bool:
        """Whether a dot-walk to a ``value`` field reaches a record that is
        not shown to be something other than a credential-type property."""
        type_keys = keys.get(reference + "type", [])
        class_keys = keys.get(reference + "sys_class_name", [])
        credential = _credential(row, type_keys)
        classes = [_stored(row[key]) for key in class_keys]
        if credential is None and PROPERTY_TABLE not in classes:
            # No plain type: returned only if the class names another table,
            # or the record has neither field (no property, or both hidden).
            elsewhere = bool(classes) and all(classes)
            unmarked = not (type_keys or class_keys)
            return not (elsewhere or unmarked)
        return credential is not False


# Columns of sys_properties that its parent table does not have: a write that
# names one through the parent could only be meant for a property.
_PARENT_TABLE = "sys_metadata"
_PROPERTY_ONLY = ("type", "value")


def check_property_write(table_name: str, data: Any, *, update: bool) -> None:
    """Refuse a write that could make a credential-type property readable.

    On ``sys_properties`` every key must be a plain column name, so no
    spelling of one reaches the instance unchecked, and an update that sets
    ``type`` to anything but a credential type is refused: it would turn the
    stored value into an ordinary one for the echo and every later read.
    ``sys_metadata``, the table it extends, has neither a ``type`` nor a
    ``value`` column, so a write there that names one is refused outright:
    whether the instance would pass it on to the property was not tested.
    """
    table = _name(table_name)
    if table not in (PROPERTY_TABLE, _PARENT_TABLE) or not isinstance(data, dict):
        return
    odd = [key for key in data if not (isinstance(key, str) and _COLUMN_RE.match(key))]
    if odd:
        raise PolicyError(
            f"On {table}, the keys of data= must be plain field names "
            "(lowercase letters, digits and underscores): "
            + _count(len(odd), "key is", "keys are")
            + " not."
        )
    if table == _PARENT_TABLE:
        if any(key in data for key in _PROPERTY_ONLY):
            raise PolicyError(
                "sys_metadata has no type or value field of its own: a write "
                "that sets one could only reach a record of a table that "
                "extends it, such as a system property, and this server "
                "doesn't change those through the parent table."
            )
        return
    if update and "type" in data and not _is_credential_type(_stored(data["type"])):
        raise PolicyError(
            "This server doesn't change a system property's type to a "
            "non-credential one: if the property is credential-type "
            "(password, password2), its value would be returned from then "
            "on. Change the type on the instance itself."
        )


def check_aggregate(table_name: str, **field_lists: Optional[str]) -> None:
    """Refuse a Stats API call on a field a row read would have withheld.

    The Stats API returns group keys, minima and maxima as bare values, with
    no row to read a type from, so these are refused: ``value`` on
    ``sys_properties``, the old and new values of the audit and history
    tables, and a dot-walk to any field of those names (it may reach a
    property, or a row that records one). A name counts wherever one of
    these is a segment of it.
    """
    table = _name(table_name)
    copies = _COPIES[table][2] if table in _COPIES else ()
    for argument, fields in field_lists.items():
        for name in _names(fields):
            for reference, field in _watched(name):
                if reference and field == "value":
                    raise PolicyError(
                        f"{argument}= can't name {name[:60]}: a dot-walk to a "
                        "value field may reach a credential-type system "
                        "property, and the Stats API returns values without the "
                        "type that would say so. Read the rows with list_records "
                        "and fields= instead: it checks each row."
                    )
                if reference:
                    raise PolicyError(
                        f"{argument}= can't name {name[:60]}: a dot-walk to an "
                        "old or new value may reach a row that records a system "
                        "property's value. Read the rows with list_records and "
                        "fields= instead: it checks each row."
                    )
                if table == PROPERTY_TABLE and field == "value":
                    raise PolicyError(
                        f"{argument}= can't name {name[:60]} on sys_properties: "
                        "it would return property values, credential-type ones "
                        "included. Group by name or type, or read the rows with "
                        "get_system_properties or list_records, which withhold "
                        "credential-type values."
                    )
                if field in copies:
                    raise PolicyError(
                        f"{argument}= can't name {name[:60]} on {table}: the "
                        "rows that record a change to a system property hold its "
                        "value, credential-type ones included. Read the rows "
                        "with list_records and fields= instead: it withholds "
                        "those."
                    )


def refuse_value_walk(argument: str, fields: Optional[str]) -> None:
    """Refuse a dot-walk to a ``value`` field, or to an old or new value,
    where no row guard runs."""
    for name in _names(fields):
        if any(reference for reference, _ in _watched(name)):
            raise PolicyError(
                f"{argument}= can't name {name[:60]}: such a dot-walk may reach "
                "a credential-type system property's value. Read it with "
                "list_records and fields= instead: it checks each row."
            )
