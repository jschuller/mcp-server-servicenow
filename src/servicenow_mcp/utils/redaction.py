"""Credential-type system property values are never returned.

``sys_properties.value`` is a string column: whether a row's value is a
credential depends on the row's ``type`` (``password``, ``password2``). The
Table API returns those values to an identity that can read the table, with
every ``sysparm_display_value``. Every tool that returns rows builds a
``Guard`` for its request and applies it to the rows before they leave:

- a ``sys_properties`` row: ``value`` is replaced with ``REDACTED`` when the
  type is credential-type, and also when the type is missing, empty or not a
  string (an ACL can hide it), so an unreadable type fails closed;
- a dot-walk to a property from another table (``property.value``): the same,
  with the type read from ``<reference>.type`` and the table from
  ``<reference>.sys_class_name``;
- the instance's own copies of a property value: the old and new values of an
  audit or history row for ``sys_properties.value`` (the row carries no type,
  so all of them), and any field that holds a property's record XML, such as
  an update set payload.

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

from servicenow_mcp.middleware.policy import PolicyError

PROPERTY_TABLE = "sys_properties"
REDACTED = "[redacted: system property value withheld as credential-type]"

# Tables whose rows copy a field's old and new values: the field that names
# the changed table, the one that names the changed field, and the copies.
_COPIES: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    "sys_audit": ("tablename", "fieldname", ("oldvalue", "newvalue")),
    "sys_history_line": (
        "set.table",
        "field",
        ("old", "old_value", "new", "new_value"),
    ),
}
# A property's record XML (an update set or version payload, a deleted
# record): <sys_properties action="..."> ... <type>password2</type> ...
_XML_RECORD_RE = re.compile(r"<sys_properties[\s>].*?(?:</sys_properties>|\Z)", re.S)
_XML_TYPE_RE = re.compile(r"<type>([^<]*)</type>")
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


def _walks_to_value(name: str) -> bool:
    return name.endswith(".value")


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
    A missing or empty type is unknown, not "string".
    """
    if not stored:
        return None
    return stored.startswith("password")


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


def _holds_credential_xml(text: str) -> bool:
    """Whether a string holds a property's record XML that may be a credential.

    Each ``<sys_properties>`` record is judged on its own: True unless every
    one has exactly one plain ``<type>`` that is not credential-type.
    """
    if PROPERTY_TABLE not in text:
        return False
    for record in _XML_RECORD_RE.findall(text):
        types = _XML_TYPE_RE.findall(record)
        if len(types) != 1 or _is_credential_type(_stored(types[0])) is not False:
            return True
    return False


def scrub(value: Any) -> Tuple[Any, int]:
    """``value`` with every string that holds credential property XML
    replaced by the marker, and how many were replaced. Lists and objects
    are changed in place."""
    if isinstance(value, str):
        return (REDACTED, 1) if _holds_credential_xml(value) else (value, 0)
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
                + " whose type is empty or did not come back (an ACL can hide "
                "it): without a readable type the value is treated as "
                "credential-type."
            )
        for field, rows in self.walked.items():
            parts.append(
                f"Withheld {field} in {_count(rows, 'row', 'rows')}: the dot-walk "
                "reaches a record whose type is password or password2 (a "
                "credential-type system property), or a system property whose "
                "type did not come back."
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
                + " the record XML of a system property whose type is password, "
                "password2 or not readable (an update set payload, for example)."
            )
        if value_filter and (self.credential or self.unknown):
            parts.append(
                "query= filters on value and matched a withheld row, so the match "
                "itself says something about that value: withheld is not the same "
                "as impossible to infer. Don't use value filters to work out a "
                "credential."
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
        requested = _names(fields)
        helpers: List[str] = []
        if self.table == PROPERTY_TABLE:
            helpers.append("type")
        if self.table in _COPIES:
            helpers.extend(_COPIES[self.table][:2])
        walks = [name for name in requested if _walks_to_value(name)]
        for name in walks:
            reference = name[: -len("value")]
            helpers += [reference + "sys_class_name", reference + "type"]
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
        watched = self.table == PROPERTY_TABLE or self.table in _COPIES or bool(walks)
        # A display label is not the stored type: read both, return one.
        self._reduce = watched and display_value == "true"
        self.display_value = "all" if self._reduce else display_value

    def apply(
        self, rows: Sequence[Any], query_names: Sequence[str] = ()
    ) -> Optional[str]:
        """Withhold in place, drop the helper fields, and return the warning
        for the result, or None when nothing was withheld."""
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
        return withheld.warning(self.table == PROPERTY_TABLE and "value" in query_names)

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
        for name in [name for name in keys if _walks_to_value(name)]:
            reference = name[: -len("value")]
            credential = _credential(row, keys.get(reference + "type", []))
            classes = [
                _stored(row[key]) for key in keys.get(reference + "sys_class_name", [])
            ]
            if credential or (PROPERTY_TABLE in classes and credential is None):
                hits = [_withhold(row, key) for key in keys[name]]
                if any(hits):
                    withheld.walked[name] = withheld.walked.get(name, 0) + 1
        if self.table in _COPIES:
            table_field, field_field, copies = _COPIES[self.table]
            if _is(row, keys.get(table_field, []), PROPERTY_TABLE) and _is(
                row, keys.get(field_field, []), "value"
            ):
                hits = [
                    _withhold(row, key) for name in copies for key in keys.get(name, [])
                ]
                withheld.copies += any(hits)
        for key in row:
            row[key], found = scrub(row[key])
            withheld.xml += bool(found)


def check_property_write(table_name: str, data: Any) -> None:
    """Refuse an update that would make a credential-type property readable.

    A write that sets ``type`` to anything but a credential type would turn
    the stored value into an ordinary one for the echo and every later read.
    """
    if _name(table_name) != PROPERTY_TABLE or not isinstance(data, dict):
        return
    for key, value in data.items():
        if _name(key) == "type" and not _is_credential_type(_stored(value)):
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
    ``sys_properties``, a dot-walk to any ``value`` field (it may reach a
    property), and the old and new values of the audit and history tables.
    """
    table = _name(table_name)
    for argument, fields in field_lists.items():
        for name in _names(fields):
            if _walks_to_value(name):
                raise PolicyError(
                    f"{argument}= can't name {name[:60]}: a dot-walk to a value "
                    "field may reach a credential-type system property, and the "
                    "Stats API returns values without the type that would say so. "
                    "Read the rows with list_records and fields= instead: it "
                    "checks each row."
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
    """Refuse a dot-walk to a ``value`` field where no row guard runs."""
    for name in _names(fields):
        if _walks_to_value(name):
            raise PolicyError(
                f"{argument}= can't name {name[:60]}: a dot-walk to a value field "
                "may reach a credential-type system property. Read it with "
                "list_records and fields= instead: it checks each row."
            )
