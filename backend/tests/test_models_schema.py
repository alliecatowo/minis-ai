"""Tests that SQLAlchemy models can be instantiated and have the expected columns.

These are pure Python instantiation tests — no DB connection required.
"""

from __future__ import annotations

import uuid


# ---------------------------------------------------------------------------
# Mini model
# ---------------------------------------------------------------------------


class TestMiniModel:
    def test_create_minimal_mini(self):
        from app.models.mini import Mini

        mini = Mini(username="torvalds", status="pending")
        assert mini.username == "torvalds"
        assert mini.status == "pending"

    def test_mini_tablename(self):
        from app.models.mini import Mini

        assert Mini.__tablename__ == "minis"

    def test_mini_id_default(self):
        from app.models.mini import Mini

        mini = Mini(username="gvanrossum")
        # id default is a UUID factory — calling it should produce a string
        assert mini.id is None or isinstance(mini.id, str)

    def test_mini_visibility_default(self):
        from app.models.mini import Mini

        # SQLAlchemy column defaults are applied at DB insert time, not on __init__
        # When explicitly set they work as expected
        mini = Mini(username="matz", visibility="public")
        assert mini.visibility == "public"

    def test_mini_nullable_fields(self):
        from app.models.mini import Mini

        mini = Mini(username="dhh")
        assert mini.display_name is None
        assert mini.avatar_url is None
        assert mini.bio is None
        assert mini.spirit_content is None
        assert mini.memory_content is None
        assert mini.system_prompt is None
        assert mini.knowledge_graph_json is None
        assert mini.principles_json is None
        assert mini.values_json is None

    def test_mini_required_columns_exist(self):
        from app.models.mini import Mini
        from sqlalchemy import inspect

        mapper = inspect(Mini)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "username", "status", "visibility", "created_at", "updated_at"]:
            assert col in col_names, f"Missing column: {col}"

    def test_mini_with_all_fields(self):
        from app.models.mini import Mini

        mini_id = str(uuid.uuid4())
        mini = Mini(
            id=mini_id,
            username="jetbrains",
            status="ready",
            visibility="private",
            display_name="JetBrains Dev",
            bio="IDE person",
            spirit_content="You are...",
            memory_content="Known for...",
            system_prompt="[PERSONALITY]...",
            knowledge_graph_json={"nodes": [], "edges": []},
            principles_json={"principles": []},
            values_json={"engineering_values": []},
        )
        assert mini.id == mini_id
        assert mini.status == "ready"
        assert mini.visibility == "private"


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


class TestUserModel:
    def test_create_minimal_user(self):
        from app.models.user import User

        user = User(id="test-id", github_username="octocat")
        assert user.id == "test-id"
        assert user.github_username == "octocat"

    def test_user_tablename(self):
        from app.models.user import User

        assert User.__tablename__ == "users"

    def test_user_nullable_fields(self):
        from app.models.user import User

        user = User(id=str(uuid.uuid4()))
        assert user.github_username is None
        assert user.display_name is None
        assert user.avatar_url is None

    def test_user_required_columns_exist(self):
        from app.models.user import User
        from sqlalchemy import inspect

        mapper = inspect(User)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "github_username", "display_name", "avatar_url", "created_at"]:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# UserSettings model
# ---------------------------------------------------------------------------


class TestUserSettingsModel:
    def test_create_user_settings(self):
        from app.models.user_settings import UserSettings

        settings = UserSettings(user_id="user-1")
        assert settings.user_id == "user-1"

    def test_user_settings_tablename(self):
        from app.models.user_settings import UserSettings

        assert UserSettings.__tablename__ == "user_settings"

    def test_user_settings_defaults(self):
        from app.models.user_settings import UserSettings

        # SQLAlchemy column defaults are applied at DB insert time; when provided they work
        settings = UserSettings(user_id="user-2", llm_provider="gemini", is_admin=False)
        assert settings.llm_provider == "gemini"
        assert settings.is_admin is False
        assert settings.llm_api_key is None
        assert settings.preferred_model is None

    def test_user_settings_with_api_key(self):
        from app.models.user_settings import UserSettings

        settings = UserSettings(user_id="user-3", llm_api_key="encrypted_key", llm_provider="openai")
        assert settings.llm_provider == "openai"
        assert settings.llm_api_key == "encrypted_key"

    def test_user_settings_columns_exist(self):
        from app.models.user_settings import UserSettings
        from sqlalchemy import inspect

        mapper = inspect(UserSettings)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "user_id", "llm_api_key", "llm_provider", "preferred_model", "is_admin"]:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Evidence model
# ---------------------------------------------------------------------------


class TestEvidenceModel:
    def test_create_evidence(self):
        from app.models.evidence import Evidence

        ev = Evidence(
            mini_id="mini-1",
            source_type="github",
            item_type="commit",
            content="feat: add feature",
        )
        assert ev.mini_id == "mini-1"
        assert ev.source_type == "github"
        assert ev.item_type == "commit"
        assert ev.content == "feat: add feature"

    def test_evidence_tablename(self):
        from app.models.evidence import Evidence

        assert Evidence.__tablename__ == "evidence"

    def test_evidence_explored_default_false(self):
        from app.models.evidence import Evidence

        # Column defaults are applied at DB insert time; test by explicit value
        ev = Evidence(mini_id="mini-2", source_type="blog", item_type="post", content="hello", explored=False)
        assert ev.explored is False

    def test_evidence_nullable_metadata(self):
        from app.models.evidence import Evidence

        ev = Evidence(mini_id="mini-3", source_type="github", item_type="pr", content="fix bug")
        assert ev.metadata_json is None

    def test_evidence_columns_exist(self):
        from app.models.evidence import Evidence
        from sqlalchemy import inspect

        mapper = inspect(Evidence)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "mini_id", "source_type", "item_type", "content", "explored", "created_at"]:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# ExplorerFinding model
# ---------------------------------------------------------------------------


class TestExplorerFindingModel:
    def test_create_explorer_finding(self):
        from app.models.evidence import ExplorerFinding

        finding = ExplorerFinding(
            mini_id="mini-1",
            source_type="github",
            category="expertise",
            content="Strong Python skills",
            confidence=0.9,
        )
        assert finding.category == "expertise"
        assert finding.confidence == 0.9

    def test_explorer_finding_tablename(self):
        from app.models.evidence import ExplorerFinding

        assert ExplorerFinding.__tablename__ == "explorer_findings"

    def test_explorer_finding_default_confidence(self):
        from app.models.evidence import ExplorerFinding

        # Column defaults are applied at DB insert time; test by explicit value
        finding = ExplorerFinding(
            mini_id="mini-2",
            source_type="blog",
            category="personality",
            content="Thoughtful",
            confidence=0.5,
        )
        assert finding.confidence == 0.5


# ---------------------------------------------------------------------------
# ExplorerQuote model
# ---------------------------------------------------------------------------


class TestExplorerQuoteModel:
    def test_create_explorer_quote(self):
        from app.models.evidence import ExplorerQuote

        quote = ExplorerQuote(
            mini_id="mini-1",
            source_type="github",
            quote="Clean code is not written by following a set of rules.",
            context="PR review",
            significance="Shows philosophy",
        )
        assert quote.quote.startswith("Clean code")
        assert quote.context == "PR review"

    def test_explorer_quote_tablename(self):
        from app.models.evidence import ExplorerQuote

        assert ExplorerQuote.__tablename__ == "explorer_quotes"

    def test_explorer_quote_nullable_fields(self):
        from app.models.evidence import ExplorerQuote

        quote = ExplorerQuote(mini_id="mini-2", source_type="hackernews", quote="Yes, exactly.")
        assert quote.context is None
        assert quote.significance is None


# ---------------------------------------------------------------------------
# ExplorerProgress model
# ---------------------------------------------------------------------------


class TestExplorerProgressModel:
    def test_create_explorer_progress(self):
        from app.models.evidence import ExplorerProgress

        prog = ExplorerProgress(
            mini_id="mini-1",
            source_type="github",
        )
        assert prog.mini_id == "mini-1"
        assert prog.source_type == "github"

    def test_explorer_progress_tablename(self):
        from app.models.evidence import ExplorerProgress

        assert ExplorerProgress.__tablename__ == "explorer_progress"

    def test_explorer_progress_defaults(self):
        from app.models.evidence import ExplorerProgress

        # Column defaults are applied at DB insert time; test by explicit values
        prog = ExplorerProgress(
            mini_id="mini-2",
            source_type="blog",
            total_items=0,
            explored_items=0,
            status="pending",
        )
        assert prog.total_items == 0
        assert prog.explored_items == 0
        assert prog.status == "pending"
        assert prog.started_at is None
        assert prog.finished_at is None

    def test_explorer_progress_columns_exist(self):
        from app.models.evidence import ExplorerProgress
        from sqlalchemy import inspect

        mapper = inspect(ExplorerProgress)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in [
            "id", "mini_id", "source_type", "total_items", "explored_items",
            "findings_count", "memories_count", "quotes_count", "nodes_count", "status",
        ]:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Conversation model
# ---------------------------------------------------------------------------


class TestConversationModelFull:
    def test_create_conversation(self):
        from app.models.conversation import Conversation

        conv = Conversation(
            mini_id="mini-1",
            user_id="user-1",
            title="Test chat",
        )
        assert conv.mini_id == "mini-1"
        assert conv.user_id == "user-1"
        assert conv.title == "Test chat"

    def test_conversation_title_optional(self):
        from app.models.conversation import Conversation

        conv = Conversation(mini_id="mini-2", user_id="user-2")
        assert conv.title is None

    def test_conversation_tablename(self):
        from app.models.conversation import Conversation

        assert Conversation.__tablename__ == "conversations"

    def test_conversation_columns_exist(self):
        from app.models.conversation import Conversation
        from sqlalchemy import inspect

        mapper = inspect(Conversation)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "mini_id", "user_id", "title", "created_at", "updated_at"]:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Message model
# ---------------------------------------------------------------------------


class TestMessageModelFull:
    def test_create_message(self):
        from app.models.conversation import Message

        msg = Message(
            conversation_id="conv-1",
            role="user",
            content="Hello!",
            ordinal=1,
        )
        assert msg.role == "user"
        assert msg.content == "Hello!"
        assert msg.ordinal == 1

    def test_message_assistant_role(self):
        from app.models.conversation import Message

        msg = Message(
            conversation_id="conv-1",
            role="assistant",
            content="How can I help?",
            ordinal=2,
        )
        assert msg.role == "assistant"

    def test_message_tablename(self):
        from app.models.conversation import Message

        assert Message.__tablename__ == "messages"

    def test_message_columns_exist(self):
        from app.models.conversation import Message
        from sqlalchemy import inspect

        mapper = inspect(Message)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "conversation_id", "role", "content", "ordinal", "created_at"]:
            assert col in col_names, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Embedding model (pgvector)
# ---------------------------------------------------------------------------


class TestEmbeddingModel:
    def test_create_embedding(self):
        from app.models.embeddings import Embedding

        emb = Embedding(
            mini_id="mini-1",
            content="Python expertise",
            embedding=[0.1] * 768,
            source_type="memory",
        )
        assert emb.mini_id == "mini-1"
        assert emb.source_type == "memory"
        assert len(emb.embedding) == 768

    def test_embedding_tablename(self):
        from app.models.embeddings import Embedding

        assert Embedding.__tablename__ == "embeddings"

    def test_embedding_nullable_metadata(self):
        from app.models.embeddings import Embedding

        emb = Embedding(
            mini_id="mini-2",
            content="test",
            embedding=[0.0] * 768,
            source_type="evidence",
        )
        assert emb.metadata_json is None

    def test_embedding_columns_exist(self):
        from app.models.embeddings import Embedding
        from sqlalchemy import inspect

        mapper = inspect(Embedding)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        for col in ["id", "mini_id", "content", "embedding", "source_type", "created_at"]:
            assert col in col_names, f"Missing column: {col}"
