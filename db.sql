-- user table
CREATE TABLE "user" (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    phone VARCHAR(15) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at timestamptz DEFAULT now()
);

-- conversation table
CREATE TABLE "conversation" (
    id BIGSERIAL PRIMARY KEY,
    phone VARCHAR(15) NOT NULL UNIQUE,
    name TEXT,
    last_message_id BIGINT,
    human_intervention_required BOOLEAN NOT NULL DEFAULT FALSE
);

-- index on phone for faster lookups
CREATE INDEX idx_conversation_phone ON "conversation"(phone);

-- many to many relationship table between users and conversations
CREATE TABLE "user_conversation" (
    user_id INT NOT NULL,
    conversation_id BIGINT NOT NULL,
    PRIMARY KEY (user_id, conversation_id),
    CONSTRAINT fk_user FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE,
    CONSTRAINT fk_conversation FOREIGN KEY (conversation_id) REFERENCES "conversation"(id) ON DELETE CASCADE
);

-- enums
CREATE TYPE message_direction AS ENUM ('inbound', 'outbound');

CREATE TYPE message_status AS ENUM ('pending', 'sent', 'delivered', 'read', 'failed');

CREATE TYPE sender AS ENUM ('customer', 'ai', 'operator');

-- message table
CREATE TABLE "message" (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    direction message_direction NOT NULL,
    sender_type sender NOT NULL, -- message created by a customer or AI or operator(user)
    sender_id INT, -- user id, if the sender is an operator. Else null
    external_id TEXT, -- provider message id
    has_text BOOLEAN NOT NULL DEFAULT TRUE,
    message_text TEXT,
    media_info JSONB, -- provider media id, mime type and media description, null if no media
    status message_status NOT NULL DEFAULT 'pending',
    provider_ts timestamptz,
    created_at timestamptz DEFAULT now(),
    extra_metadata JSONB,
    CONSTRAINT fk_conversation FOREIGN KEY(conversation_id) REFERENCES "conversation"(id) ON DELETE CASCADE
);

-- index on conversation id for faster lookups
CREATE INDEX idx_message_conversation_id ON "message"(conversation_id);

-- foreign key constraint for last message in conversation table
ALTER TABLE
    "conversation"
ADD
    CONSTRAINT fk_last_message FOREIGN KEY(last_message_id) REFERENCES "message"(id) ON DELETE
SET
    NULL;

-- trigger function to update last_message_id in conversation table on new message insert
CREATE OR REPLACE FUNCTION update_last_message()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE "conversation"
    SET last_message_id = NEW.id
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- trigger to call the function after insert on message table
CREATE TRIGGER trg_update_last_message
AFTER INSERT ON "message"
FOR EACH ROW
EXECUTE PROCEDURE update_last_message();


-- trigger function to notify on new message insert
CREATE OR REPLACE FUNCTION notify_new_message_entry()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('new_message_entry_channel', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- trigger to call the function after insert on message table
CREATE TRIGGER trg_notify_new_message_entry
AFTER INSERT ON "message"
FOR EACH ROW
EXECUTE PROCEDURE notify_new_message_entry();

