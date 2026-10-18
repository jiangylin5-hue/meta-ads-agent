from backend.db.schema import metadata
from scripts import db_ops
from scripts.check_database_schema import check_schema


def test_database_schema_relationships_are_declared() -> None:
    assert check_schema() == []


def test_database_schema_uses_jsonb_for_payload_fields() -> None:
    for table_name in ["meta_account_snapshots", "clients", "execution_logs"]:
        table = metadata.tables[table_name]
        json_columns = [column.name for column in table.columns if "json" in column.name]
        assert json_columns, table_name


def test_conversation_memory_schema_uses_pgvector_and_scope_indexes() -> None:
    table = metadata.tables["conversation_memory_chunks"]

    assert table.c.embedding.type.get_col_spec() == "vector(1536)"
    assert table.c.session_id.foreign_keys
    assert table.c.message_id.foreign_keys
    assert "ix_conversation_memory_embedding" in {index.name for index in table.indexes}


def test_database_operation_script_runs_offline_schema_check(capsys) -> None:
    assert db_ops.main(["check-schema"]) == 0

    captured = capsys.readouterr()
    assert "Database schema check passed." in captured.out


def test_database_operation_script_refuses_destructive_downgrade(capsys) -> None:
    assert db_ops.main(["downgrade"]) == 2

    captured = capsys.readouterr()
    assert "Refusing destructive downgrade" in captured.err
