# Copyright 2023 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""schedule id

Revision ID: cf21882f938e
Revises: 11f8dd2dc9fe
Create Date: 2020-10-07 11:21:49.223077

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cf21882f938e"
down_revision = "11f8dd2dc9fe"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("schedules_v2") as batch_op:
        batch_op.add_column(sa.Column("id", sa.Integer(), nullable=False))
        batch_op.create_primary_key("pk_schedules_v2", ["id"])
        batch_op.create_unique_constraint("_schedules_v2_uc", ["project", "name"])


def downgrade():
    with op.batch_alter_table("schedules_v2") as batch_op:
        batch_op.drop_constraint("_schedules_v2_uc", type_="unique")
        batch_op.create_primary_key("pk_schedules_v2", ["name", "project"])
        batch_op.drop_column("id")
