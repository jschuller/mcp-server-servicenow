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
letters, digits and underscores, joined by single dots.

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
# attributes or a namespace prefix, the "<" plain or escaped once for XML or
# JSON. Not <sys_properties_category>.
_XML_RECORD_RE = re.compile(
    r"(?:<|&lt;|\\u003c)(?:[\w.\-]+:)?sys_properties(?!\w)", re.I
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
            reference, dot, last = name.rpartition(".")
            if last == "value" and dot:
                helpers += [f"{reference}.sys_class_name", f"{reference}.type"]
            elif last in _COPY_OF and dot:
                table_field, field_field, _ = _COPY_OF[last]
                helpers += [f"{reference}.{table_field}", f"{reference}.{field_field}"]
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
        if self.table == PROPERTY_TABLE and "value" in keys:
            credential = _credential(row, keys.get("type", []))
            hits = [
                credential is not False and _withhold(row, key) for key in keys["value"]
            ]
            if any(hits):
                group = withheld.unknown if credential is None else withheld.credential
                group.append(_label(row, keys))
        copied = False
        if self.table in _COPIES:
            copied = self._copies(row, keys, "", _COPIES[self.table], direct=True)
        for name in list(keys):
            reference, dot, last = name.rpartition(".")
            if not dot:
                continue
            if last == "value":
                self._walk(row, keys, name, reference, withheld)
            elif last in _COPY_OF:
                copy = _COPY_OF[last]
                copied |= self._copies(row, keys, f"{reference}.", copy, direct=False)
        withheld.copies += copied
        for key in row:
            row[key], found = scrub(row[key])
            withheld.xml += bool(found)

    @staticmethod
    def _walk(
        row: Dict[str, Any],
        keys: Dict[str, List[str]],
        name: str,
        reference: str,
        withheld: _Withheld,
    ) -> None:
        """A dot-walk to a ``value`` field: withheld unless the record it
        reaches is shown to be no credential-type property."""
        type_keys = keys.get(f"{reference}.type", [])
        class_keys = keys.get(f"{reference}.sys_class_name", [])
        credential = _credential(row, type_keys)
        classes = [_stored(row[key]) for key in class_keys]
        if credential is None and PROPERTY_TABLE not in classes:
            # No plain type: returned only if the class names another table,
            # or the record has neither field (no property, or both hidden).
            elsewhere = bool(classes) and all(classes)
            unmarked = not (type_keys or class_keys)
            credential = False if elsewhere or unmarked else None
        if credential is not False:
            hits = [_withhold(row, key) for key in keys[name]]
            if any(hits):
                withheld.walked[name] = withheld.walked.get(name, 0) + 1

    @staticmethod
    def _copies(
        row: Dict[str, Any],
        keys: Dict[str, List[str]],
        reference: str,
        copy: _Copy,
        *,
        direct: bool,
    ) -> bool:
        """The old and new values of an audit or history row, read from its
        table (``reference`` empty) or through a dot-walk. A row that doesn't
        say which table and field it records fails closed; a walked record
        with neither of those fields is no audit row."""
        table_field, field_field, copies = copy
        table_keys = keys.get(reference + table_field, [])
        field_keys = keys.get(reference + field_field, [])
        if not direct and not (table_keys or field_keys):
            return False
        if not (_is(row, table_keys, PROPERTY_TABLE) and _is(row, field_keys, "value")):
            return False
        hits = [
            _withhold(row, key)
            for name in copies
            for key in keys.get(reference + name, [])
        ]
        return any(hits)


def check_property_write(table_name: str, data: Any, *, update: bool) -> None:
    """Refuse a write to ``sys_properties`` that could make a credential-type
    property readable.

    Every key must be a plain column name, so no spelling of one reaches the
    instance unchecked. An update that sets ``type`` to anything but a
    credential type is refused: it would turn the stored value into an
    ordinary one for the echo and every later read.
    """
    if _name(table_name) != PROPERTY_TABLE or not isinstance(data, dict):
        return
    odd = [key for key in data if not (isinstance(key, str) and _COLUMN_RE.match(key))]
    if odd:
        raise PolicyError(
            "On sys_properties, the keys of data= must be plain field names "
            "(lowercase letters, digits and underscores): "
            + _count(len(odd), "key is", "keys are")
            + " not."
        )
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
    property, or a row that records one).
    """
    table = _name(table_name)
    for argument, fields in field_lists.items():
        for name in _names(fields):
            reference, dot, last = name.rpartition(".")
            if dot and last == "value":
                raise PolicyError(
                    f"{argument}= can't name {name[:60]}: a dot-walk to a value "
                    "field may reach a credential-type system property, and the "
                    "Stats API returns values without the type that would say so. "
                    "Read the rows with list_records and fields= instead: it "
                    "checks each row."
                )
            if dot and last in _COPY_OF:
                raise PolicyError(
                    f"{argument}= can't name {name[:60]}: a dot-walk to an old "
                    "or new value may reach a row that records a system "
                    "property's value. Read the rows with list_records and "
                    "fields= instead: it checks each row."
                )
            if table == PROPERTY_TABLE and name == "value":
                raise PolicyError(
                    f"{argument}= can't name value on sys_properties: it would "
                    "return property values, credential-type ones included. "
                    "Group by name or type, or read the rows with "
                    "get_system_properties or list_records, which withhold "
                    "credential-type values."
                )
            if table in _COPIES and name in _COPIES[table][2]:
                raise PolicyError(
                    f"{argument}= can't name {name} on {table}: the rows that "
                    "record a change to a system property hold its value, "
                    "credential-type ones included. Read the rows with "
                    "list_records and fields= instead: it withholds those."
                )


def refuse_value_walk(argument: str, fields: Optional[str]) -> None:
    """Refuse a dot-walk to a ``value`` field, or to an old or new value,
    where no row guard runs."""
    for name in _names(fields):
        reference, dot, last = name.rpartition(".")
        if dot and (last == "value" or last in _COPY_OF):
            raise PolicyError(
                f"{argument}= can't name {name[:60]}: such a dot-walk may reach "
                "a credential-type system property's value. Read it with "
                "list_records and fields= instead: it checks each row."
            )
