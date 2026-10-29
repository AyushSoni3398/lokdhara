"""Topics: what a recording is about, from a list admins can extend (ADR-030).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-29

`topics` holds the list shown to contributors, with an English and a Hindi label. Admins add
topics and retire them; a retired topic stays on the items that have it but is not offered
any more. Keys never change, so exported data keeps its meaning. `submissions.topics` holds
the keys chosen for an item; the app checks them against this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Provisional list for Q-X5, to be checked by a linguist and the community.
INITIAL_TOPICS = (
    ("agriculture", "Agriculture and farming", "खेती-बाड़ी"),
    ("forest_and_nature", "Forest and nature", "जंगल और प्रकृति"),
    ("animals_and_livestock", "Animals and livestock", "पशु और मवेशी"),
    ("water_and_weather", "Water, weather and seasons", "पानी, मौसम और ऋतुएँ"),
    ("health_and_medicine", "Health and medicine", "स्वास्थ्य और इलाज"),
    ("food_and_cooking", "Food and cooking", "खाना और रसोई"),
    ("family_and_relations", "Family and relations", "परिवार और रिश्ते"),
    ("daily_life", "Daily life", "रोज़मर्रा का जीवन"),
    ("education", "Education and school", "शिक्षा और स्कूल"),
    ("governance", "Governance and village council", "शासन और ग्राम सभा"),
    ("law_and_rights", "Law, land and rights", "कानून, ज़मीन और अधिकार"),
    ("market_and_money", "Market, money and trade", "बाज़ार, पैसा और व्यापार"),
    ("work_and_crafts", "Work and crafts", "काम और हुनर"),
    ("festivals_and_rituals", "Festivals and rituals", "त्योहार और रीति-रिवाज"),
    ("beliefs", "Beliefs and worship", "आस्था और पूजा"),
    ("history_and_ancestors", "History and ancestors", "इतिहास और पूर्वज"),
    ("folk_tales", "Folk tales and legends", "लोककथाएँ और किंवदंतियाँ"),
    ("music_and_dance", "Music and dance", "संगीत और नृत्य"),
    ("games_and_play", "Games and play", "खेल-कूद"),
    ("places_and_travel", "Places and travel", "जगहें और यात्रा"),
    ("numbers_and_time", "Numbers, days and time", "गिनती, दिन और समय"),
    ("technology", "Phones and technology", "फ़ोन और तकनीक"),
    ("other", "Something else", "कुछ और"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE topics (
          key         text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,39}$'),
          label_en    text NOT NULL CHECK (length(label_en) BETWEEN 1 AND 80),
          label_hi    text NOT NULL CHECK (length(label_hi) BETWEEN 1 AND 80),
          sort_order  integer NOT NULL DEFAULT 1000,
          retired_at  timestamptz,
          created_by  uuid REFERENCES users (id),
          created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    insert = sa.text(
        "INSERT INTO topics (key, label_en, label_hi, sort_order) VALUES (:key, :en, :hi, :order)"
    )
    for order, (key, english, hindi) in enumerate(INITIAL_TOPICS):
        op.execute(insert.bindparams(key=key, en=english, hi=hindi, order=order * 10))
    op.execute("ALTER TABLE submissions ADD COLUMN topics text[] NOT NULL DEFAULT '{}'")
    op.execute(
        "ALTER TABLE submissions ADD CONSTRAINT ck_submissions_topics_count "
        "CHECK (cardinality(topics) <= 10)"
    )
    op.execute("CREATE INDEX ix_submissions_topics ON submissions USING gin (topics)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_submissions_topics")
    op.execute("ALTER TABLE submissions DROP COLUMN topics")
    op.execute("DROP TABLE topics")
