"""Tests for conversation and message models.

These tests verify model construction and default values without
requiring a database connection.
"""

import uuid

from app.models.conversation import Conversation, Message


class TestConversationModel:
    def test_create_conversation(self):
        conv = Conversation(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            title="Chat about Python",
        )
        assert conv.title == "Chat about Python"
        assert conv.mini_id is not None
        assert conv.user_id is not None

    def test_conversation_title_nullable(self):
        conv = Conversation(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
        assert conv.title is None

    def test_conversation_tablename(self):
        assert Conversation.__tablename__ == "conversations"

    def test_conversation_mini_id_fk(self):
        col = Conversation.__table__.columns["mini_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "minis.id"
        assert fks[0].ondelete == "CASCADE"

    def test_conversation_user_id_fk(self):
        col = Conversation.__table__.columns["user_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "users.id"
        assert fks[0].ondelete == "CASCADE"

    def test_conversation_indexes(self):
        table = Conversation.__table__
        assert table.columns["mini_id"].index is True
        assert table.columns["user_id"].index is True


class TestMessageModel:
    def test_create_message(self):
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=str(uuid.uuid4()),
            role="user",
            content="Hello, how are you?",
            ordinal=0,
        )
        assert msg.role == "user"
        assert msg.content == "Hello, how are you?"
        assert msg.ordinal == 0

    def test_message_assistant_role(self):
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=str(uuid.uuid4()),
            role="assistant",
            content="I'm doing well, thanks!",
            ordinal=1,
        )
        assert msg.role == "assistant"
        assert msg.ordinal == 1

    def test_message_tablename(self):
        assert Message.__tablename__ == "messages"

    def test_message_conversation_id_fk(self):
        col = Message.__table__.columns["conversation_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "conversations.id"
        assert fks[0].ondelete == "CASCADE"

    def test_message_conversation_id_indexed(self):
        table = Message.__table__
        assert table.columns["conversation_id"].index is True

    def test_message_ordinal_required(self):
        col = Message.__table__.columns["ordinal"]
        assert col.nullable is False

    def test_message_role_required(self):
        col = Message.__table__.columns["role"]
        assert col.nullable is False

    def test_message_content_required(self):
        col = Message.__table__.columns["content"]
        assert col.nullable is False
