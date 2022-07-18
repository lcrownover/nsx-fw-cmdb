from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, validator
import psycopg2
import os
import logging
import sys
import re
from typing import Optional


def validate_vmname(name: str) -> str:
    valid_re = re.compile(r"^[a-zA-Z0-9-_]+$")
    if not valid_re.match(name):
        raise ValueError(f"Hostnames must match pattern: {valid_re.pattern}")
    return name


def validate_action(action: str) -> str:
    if not action in ["allow", "reject"]:
        raise ValueError(f"action must be one of: [allow, reject]")
    return action


class Entry(BaseModel):
    id: Optional[int | None] = None
    vmname: str
    comment: str
    source: str
    service: str
    action: str = "allow"
    input_source: str

    _validate_name = validator("vmname", allow_reuse=True)(validate_vmname)
    _validate_action = validator("action", allow_reuse=True)(validate_action)

    @classmethod
    def from_db_row(cls, row: tuple[str, str, str, str, str, str, str]):
        return cls(
            id=row[0],
            vmname=row[1],
            comment=row[2],
            source=row[3],
            service=row[4],
            action=row[5],
            input_source=row[6],
        )

class Status(BaseModel):
    ok: bool


logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def li(msg: str):
    logging.info(f"\t{msg}")


def ld(msg: str):
    logging.debug(f"\t{msg}")


def lw(msg: str):
    logging.warning(f"\t{msg}")


class EntryNotFoundError(Exception):
    pass


db_username = os.getenv("DB_USERNAME")
db_password = os.getenv("DB_PASSWORD")
db_port = 5432
db_name = "cmdb"

app = FastAPI()


try:
    conn = psycopg2.connect(
        database=db_name,
        user=db_username,
        password=db_password,
        host="nsx-fw-cmdb-db",
        port=db_port,
    )
except Exception as e:
    sys.stderr.write(f"Failed to connect to database. It might not be up yet.\n{e}\n")
    exit(1)

cur = conn.cursor()


def db_get_entry_id(entry: Entry) -> int:
    sql = """SELECT * FROM entries WHERE
    vmname = %s AND
    comment = %s AND
    source = %s AND
    service = %s AND
    action = %s AND
    input_source = %s
    """
    cur.execute(
        sql, (entry.vmname, entry.comment, entry.source, entry.service, entry.action, entry.input_source)
    )
    data = cur.fetchone()
    if data:
        ld(f"entry '{entry}' exists")
        return data[0]  # first field is the id
    ld(f"entry '{entry}' doesnt exist")
    raise EntryNotFoundError


def db_get_entry_by_id(entry_id: int) -> Entry:
    sql = "SELECT * FROM entries WHERE id = %s"
    cur.execute(sql, (entry_id,))
    row = cur.fetchone()
    if row:
        ld(f"entry_id '{entry_id}' exists")
        ld(str(row))
        return Entry.from_db_row(row)
    ld(f"entry_id '{entry_id}' doesnt exist")
    raise EntryNotFoundError


def db_insert_entry(entry: Entry) -> int:
    try:
        entry_id = db_get_entry_id(entry)
    except:
        entry_id = None
    if entry_id:
        return entry_id
    li(f"inserting entry '{entry}'")
    sql = f"INSERT INTO entries (vmname, comment, source, service, action, input_source) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
    cur.execute(
        sql, (entry.vmname, entry.comment, entry.source, entry.service, entry.action, entry.input_source)
    )
    entry_id = cur.fetchone()[0]
    conn.commit()
    return entry_id


def db_get_all_entries() -> list[Entry]:
    entry_lookup = {}
    sql = "SELECT * FROM entries"
    cur.execute(sql)
    data = cur.fetchall()
    if not data:
        raise EntryNotFoundError
    for row in data:
        entry = Entry.from_db_row(row)
        if entry.vmname not in entry_lookup:
            entry_lookup[entry.vmname] = []
        entry_lookup[entry.vmname].append(entry)
    all_entries = []
    for entry_list in entry_lookup.values():
        all_entries.extend(entry_list)
    return all_entries


def db_get_entry(entry: Entry) -> Entry:
    try:
        entry_id = db_get_entry_id(entry)
    except EntryNotFoundError:
        raise
    sql = "SELECT * FROM entries WHERE id = %s"
    cur.execute(sql, (entry_id,))
    data = cur.fetchall()
    if not data:
        raise EntryNotFoundError
    entry = Entry.from_db_row(data[0])
    return entry


def db_get_entries_for_vm(vmname: str) -> list[Entry]:
    sql = "SELECT * FROM entries WHERE vmname = %s"
    cur.execute(sql, (vmname,))
    data = cur.fetchall()
    if not data:
        raise EntryNotFoundError
    entries = []
    for row in data:
        entries.append(Entry.from_db_row(row))
    return entries


def db_delete_entry(entry_id: int) -> None:
    sql = "DELETE FROM entries WHERE id = %s"
    cur.execute(sql, (entry_id,))
    conn.commit()


#pre_data = [
#    Entry(
#        vmname="lctest-pre-data1",
#        comment="test rule 1",
#        source="mem_uonet_DATA",
#        service="TCP:5668",
#        action="allow",
#    ),
#    Entry(
#        vmname="lctest-pre-data1",
#        comment="test rule 2",
#        source="mem_uonet_DATA",
#        service="TCP:5667",
#        action="reject",
#    ),
#    Entry(
#        vmname="lctest-pre-data1",
#        comment="test rule 3",
#        source="mem_deleteme-lctest_DATA",
#        service="SSH",
#        action="allow",
#    ),
#    Entry(
#        vmname="lctest-pre-data2",
#        comment="test rule 1",
#        source="184.171.150.123",
#        service="SSH",
#    ),
#    Entry(
#        vmname="lctest-pre-data2",
#        comment="test rule 2",
#        source="128.223.60.0/24",
#        service="HTTPS",
#    ),
#]
#
## prepopulate data
#for entry in pre_data:
#    ld(f"populating pre_data: {entry}")
#    try:
#        entry_id = db_get_entry_id(entry)
#    except EntryNotFoundError:
#        entry_id = db_insert_entry(entry)


###
# Status endpoint
@app.get("/status/")
async def get_status():
    return Status(ok=True)
#
###


###
#
# /entries
#   POST new entry
#   GET all entries
#
@app.get("/entries/", response_model=list[Entry])
async def get_all_entries() -> list[Entry]:
    try:
        return db_get_all_entries()
    except Exception as e:
        raise HTTPException(status_code=404, detail="No entries found")


@app.post("/entries/", response_model=Entry)
async def create_entry(entry: Entry) -> Entry:
    db_insert_entry(entry)
    entry = db_get_entry(entry)
    return entry


#
###

###
#
#   /entries/{name}
#   POST error
#   GET entry
#   DELETE entry
#
@app.get("/entries/{vmname}/", response_model=list[Entry])
async def get_entries(vmname: str) -> list[Entry]:
    try:
        return db_get_entries_for_vm(vmname)
    except:
        raise HTTPException(status_code=404, detail="No entries not found")


@app.delete("/entries/{vmname}/", response_model=list[Entry])
async def delete_entries(vmname: str) -> list[Entry]:
    try:
        entries = db_get_entries_for_vm(vmname)
        for entry in entries:
            db_delete_entry(entry.id)
        return entries
    except:
        raise HTTPException(status_code=404, detail="No entries not found")


@app.delete("/entries/{vmname}/{id}")
async def delete_entry(vmname: str, id: int):
    try:
        entry = db_get_entry_by_id(id)
        if entry.vmname != vmname:
            raise HTTPException(
                status_code=500, detail="Entry found but vmname does not match"
            )
        db_delete_entry(id)
    except EntryNotFoundError:
        raise HTTPException(status_code=404, detail="Entry not found")


#
###
