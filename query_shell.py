"""
Interactive Database Query Shell for Land Registry (SQL + NoSQL).
Usage:
    python query_shell.py
or pass queries via argument:
    python query_shell.py --sql "SELECT * FROM parcels LIMIT 5;"
    python query_shell.py --mongo "db.parcels.find().limit(5)"
"""

import sys
import os
import argparse
import json

# Add project root and backend to python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from db.connection import get_pg_connection, get_mongo_db, is_mock_mode, init_db_pools


def format_table(headers, rows):
    """Clean ASCII table renderer without external dependencies."""
    if not headers:
        return ""
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(val) if val is not None else "NULL"))

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    head_line = "| " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    output = [sep, head_line, sep]
    for row in rows:
        row_line = "| " + " | ".join((str(val) if val is not None else "NULL").ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        output.append(row_line)
    output.append(sep)
    return "\n".join(output)


def run_sql(query: str):
    """Execute a raw SQL query and print tabular results."""
    query = query.strip()
    if not query:
        return

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                if cur.description:
                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    if rows:
                        print(format_table(columns, rows))
                        print(f"({len(rows)} row(s) returned)\n")
                    else:
                        print(format_table(columns, []))
                        print("(0 rows returned)\n")
                else:
                    conn.commit()
                    print(f"Query executed successfully. Affected rows: {cur.rowcount}\n")
    except Exception as e:
        print(f"❌ SQL Error: {e}\n")


def run_nosql(command: str):
    """Execute MongoDB commands."""
    command = command.strip()
    if not command:
        return

    db = get_mongo_db()
    if db is None:
        print("❌ MongoDB is not connected or initialized.\n")
        return

    try:
        if command in ("show collections", "show tables", "collections"):
            cols = db.list_collection_names()
            print("Collections in MongoDB:")
            for c in cols:
                count = db[c].count_documents({})
                print(f"  • {c} ({count} documents)")
            print()
            return

        if not command.startswith("db."):
            print("❌ Invalid NoSQL command. Format: db.<collection>.<action>(), e.g.:")
            print("   db.parcels.find()")
            print("   db.blocks.find({\"index\": 1})")
            print("   collections\n")
            return

        parts = command[3:].split(".", 1)
        if len(parts) < 2:
            print("❌ Specify both collection and operation: db.<collection>.<operation>()\n")
            return

        col_name = parts[0].strip()
        call_part = parts[1].strip()
        col = db[col_name]

        if call_part.startswith("count"):
            count = col.count_documents({})
            print(f"Total documents in '{col_name}': {count}\n")
            return

        query_dict = {}
        if "(" in call_part and ")" in call_part:
            arg_str = call_part[call_part.find("(") + 1 : call_part.rfind(")")].strip()
            if arg_str:
                query_dict = json.loads(arg_str)

        docs = list(col.find(query_dict).limit(25))
        if not docs:
            print("(0 documents found)\n")
            return

        for i, doc in enumerate(docs, 1):
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            print(f"--- Document {i} ---")
            print(json.dumps(doc, indent=2, default=str))
        print(f"\n({len(docs)} document(s) displayed)\n")

    except Exception as e:
        print(f"❌ NoSQL Error: {e}\n")


def interactive_mode():
    init_db_pools()
    mode = "MOCK IN-MEMORY DB" if is_mock_mode() else "LIVE POSTGRESQL & MONGODB"
    print("=" * 65)
    print(f"  Land Registry Query Shell ({mode})")
    print("=" * 65)
    print("Commands:")
    print("  • Type any SQL query directly: SELECT * FROM parcels LIMIT 5;")
    print("  • Type 'tables' to list all SQL tables")
    print("  • Type 'collections' to list all MongoDB collections")
    print("  • Prefix with 'db.' for MongoDB: db.parcels.find()")
    print("  • Type 'exit' or 'quit' to close")
    print("-" * 65)

    while True:
        try:
            line = input("query> ").strip()
            if not line:
                continue
            if line.lower() in ("exit", "quit", "q"):
                print("Exiting query shell. Goodbye!")
                break
            elif line.lower() in ("tables", "\\dt"):
                run_sql("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    ORDER BY table_name;
                """)
            elif line.lower() in ("collections", "show collections"):
                run_nosql("show collections")
            elif line.startswith("db.") or line.lower().startswith("nosql:"):
                clean = line[6:].strip() if line.lower().startswith("nosql:") else line
                run_nosql(clean)
            else:
                run_sql(line)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query SQL or NoSQL database")
    parser.add_argument("--sql", help="Run SQL query directly")
    parser.add_argument("--mongo", help="Run MongoDB query directly")
    args = parser.parse_args()

    if args.sql:
        init_db_pools()
        run_sql(args.sql)
    elif args.mongo:
        init_db_pools()
        run_nosql(args.mongo)
    else:
        interactive_mode()
