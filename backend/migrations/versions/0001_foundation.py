"""Foundation: roles, private schema, tenant tables, RLS.

Revision ID: 0001
Revises:
Create Date: 2026-07-12

Written as explicit SQL rather than SQLAlchemy operations, on purpose. Alembic's
autogenerate cannot see policies, GRANTs, FORCE ROW LEVEL SECURITY, or roles --
that is, it cannot see any of the objects that actually enforce tenant
isolation. Hiding them behind an ORM DSL would suggest a safety that does not
exist. See ADR 0003 and ADR 0004.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _password(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(
            f"{var} is not set. Application role passwords are secrets and are never "
            f"hardcoded in a migration -- a password committed to git is in the history "
            f"forever."
        )
    return value


def upgrade() -> None:
    runtime_pw = _password("DIALETIQ_APP_RUNTIME_PASSWORD")
    delivery_pw = _password("DIALETIQ_APP_DELIVERY_PASSWORD")

    # ------------------------------------------------------------------
    # UUIDv7 is native in Postgres 18, which is what Neon runs.
    #
    # Every exposed identifier is a UUID, never a bigserial. A global sequence
    # lets a tenant insert two rows an hour apart, read the delta, and deduce
    # platform-wide activity volume and its competitors' campaign peaks -- the
    # German tank problem. v7 additionally keeps values time-ordered, preserving
    # index locality on the high-insert tables (campaign_recipient, event).
    #
    # Fail loudly rather than silently falling back to a hand-rolled plpgsql
    # version: getting the version bits subtly wrong would be invisible.
    # ------------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
          PERFORM uuidv7();
        EXCEPTION WHEN undefined_function THEN
          RAISE EXCEPTION 'uuidv7() is unavailable. Postgres 18+ is required.';
        END
        $$;
    """)

    # ------------------------------------------------------------------
    # Roles.
    #
    # Created HERE, by SQL -- never through the Neon console. Console-created
    # roles are members of `neon_superuser`, which carries BYPASSRLS: same name,
    # same password, and every RLS policy silently ignored. The startup guards
    # assert this has not happened.
    #
    # One LOGIN role for HTTP traffic (`app_runtime`), which switches into
    # `app_tenant` or `app_person` per transaction via SET LOCAL ROLE. Two login
    # roles would mean two SQLAlchemy pools and twice the connections against
    # Neon -- the scarcest resource we have.
    #
    # NOINHERIT is what makes this safe: app_runtime holds the grants but has
    # none of their privileges until it explicitly SET ROLEs.
    # ------------------------------------------------------------------
    #
    # The passwords reach Postgres as bind parameters and are interpolated by
    # `format(..., %L)` -- that is quote_literal, escaping done by the server.
    # DDL cannot take bind parameters directly, and hand-rolling the quoting
    # with an f-string is how injection bugs are born.
    op.execute(
        sa.text("SELECT set_config('dialetiq.runtime_pw', :pw, true)").bindparams(pw=runtime_pw)
    )
    op.execute(
        sa.text("SELECT set_config('dialetiq.delivery_pw', :pw, true)").bindparams(pw=delivery_pw)
    )
    op.execute(
        sa.text("""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_tenant') THEN
                CREATE ROLE app_tenant NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_person') THEN
                CREATE ROLE app_person NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_platform') THEN
                CREATE ROLE app_platform NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                EXECUTE format(
                    'CREATE ROLE app_runtime LOGIN NOINHERIT PASSWORD %L',
                    current_setting('dialetiq.runtime_pw')
                );
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_delivery') THEN
                EXECUTE format(
                    'CREATE ROLE app_delivery LOGIN NOINHERIT PASSWORD %L',
                    current_setting('dialetiq.delivery_pw')
                );
              END IF;
            END
            $$;
        """)
    )
    op.execute("GRANT app_tenant, app_person, app_platform TO app_runtime")
    # Drop the passwords from session state as soon as they are consumed.
    op.execute("RESET dialetiq.runtime_pw")
    op.execute("RESET dialetiq.delivery_pw")

    # ------------------------------------------------------------------
    # The private schema.
    #
    # This is the structural version of "person_id never crosses the admin API
    # boundary". A convention dies to a SELECT *, a CSV export, or a Pydantic
    # serializer without exclude. A revoked privilege does not.
    #
    # person_id is the join key that would let two competing stores correlate
    # their customer bases. app_tenant gets no USAGE here, ever.
    # ------------------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS private")
    op.execute("REVOKE ALL ON SCHEMA private FROM PUBLIC")
    op.execute(
        "GRANT USAGE ON SCHEMA public TO "
        "app_runtime, app_tenant, app_person, app_platform, app_delivery"
    )
    # app_tenant and app_platform are absent here on purpose. Neither may ever
    # reach the consumer identity graph.
    op.execute("GRANT USAGE ON SCHEMA private TO app_person, app_delivery")

    op.execute("""
        CREATE TABLE private.person (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            phone_hmac      bytea NOT NULL UNIQUE,
            phone_enc       bytea NOT NULL,
            email_hmac      bytea UNIQUE,
            email_enc       bytea,
            pepper_version  smallint NOT NULL DEFAULT 1,
            created_at      timestamptz NOT NULL DEFAULT now(),
            deleted_at      timestamptz
        );
    """)

    # A device belongs to a PERSON, not to a tenant.
    #
    # UNIQUE(fcm_token) globally -- never UNIQUE(person_id, fcm_token). A backup
    # restore or an account switch moves a token between people; with the wrong
    # constraint, one store's push for Person 1 is delivered to Person 2. That is
    # not a cross-tenant leak, it is a cross-CONSUMER leak, which is worse.
    op.execute("""
        CREATE TABLE private.device (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            person_id     uuid NOT NULL REFERENCES private.person(id) ON DELETE CASCADE,
            fcm_token     text NOT NULL UNIQUE,
            platform      text NOT NULL CHECK (platform IN ('ios', 'android')),
            last_seen_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX device_person_idx ON private.device (person_id);
    """)

    # ------------------------------------------------------------------
    # Tenant-facing tables. No person_id anywhere in this schema.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE public.tenant (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            slug           text NOT NULL UNIQUE,
            name           text NOT NULL,
            whatsapp_e164  text,
            instagram_url  text,
            branding       jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE public.staff_user (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id      uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            email          text NOT NULL,
            password_hash  text NOT NULL,
            role           text NOT NULL CHECK (role IN ('owner', 'admin', 'operator')),
            totp_secret    text,
            created_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, email)
        );
    """)

    # The only consumer identity the panel ever sees. Note: no person_id.
    op.execute("""
        CREATE TABLE public.tenant_customer (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id      uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            external_ref   text,
            consent_state  text NOT NULL CHECK (consent_state IN ('pending', 'active', 'revoked')),
            consent_source text NOT NULL CHECK (consent_source IN ('self_follow', 'invite_accept')),
            consent_at     timestamptz,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX tenant_customer_tenant_idx ON public.tenant_customer (tenant_id);
    """)

    # The bridge, in private. This is the whole privacy model in one table.
    op.execute("""
        CREATE TABLE private.person_link (
            tenant_customer_id  uuid PRIMARY KEY
                                REFERENCES public.tenant_customer(id) ON DELETE CASCADE,
            person_id           uuid NOT NULL REFERENCES private.person(id) ON DELETE CASCADE,
            UNIQUE (person_id, tenant_customer_id)
        );
        CREATE INDEX person_link_person_idx ON private.person_link (person_id);
    """)

    op.execute("""
        CREATE TABLE public.campaign (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id     uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            title         text NOT NULL,
            body          text NOT NULL,
            image_url     text,
            status        text NOT NULL CHECK (status IN ('draft', 'scheduled', 'sending', 'sent')),
            scheduled_at  timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX campaign_tenant_idx ON public.campaign (tenant_id);
    """)

    # One row per addressee, with a state machine.
    #
    # Without this, a worker that dies mid-blast and retries re-sends to every
    # recipient. At 500k devices that is not a bug, it is a press incident.
    #
    # Deliberately carries NO device_id, no fcm_token, no device count: per-device
    # FCM errors would tell a tenant that a specific consumer's device is being
    # hammered -- which is another tenant's traffic.
    op.execute("""
        CREATE TABLE public.campaign_recipient (
            id                  uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id           uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            campaign_id         uuid NOT NULL REFERENCES public.campaign(id) ON DELETE CASCADE,
            tenant_customer_id  uuid NOT NULL
                                REFERENCES public.tenant_customer(id) ON DELETE CASCADE,
            status              text NOT NULL CHECK (status IN (
                                    'pending', 'claimed', 'sent', 'delivered',
                                    'opened', 'unreachable', 'pending_retry')),
            claimed_at          timestamptz,
            sent_at             timestamptz,
            opened_at           timestamptz,
            UNIQUE (campaign_id, tenant_customer_id)
        );
        CREATE INDEX campaign_recipient_claim_idx
            ON public.campaign_recipient (campaign_id, status);
    """)

    op.execute("""
        CREATE TABLE public.lead (
            id                  uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id           uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            tenant_customer_id  uuid NOT NULL
                                REFERENCES public.tenant_customer(id) ON DELETE CASCADE,
            campaign_id         uuid REFERENCES public.campaign(id) ON DELETE SET NULL,
            payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
            status              text NOT NULL CHECK (status IN ('new', 'contacted', 'closed')),
            created_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX lead_tenant_idx ON public.lead (tenant_id);
    """)

    # The analytics foundation, and the ONE irreversible thing in this migration:
    # behaviour not recorded today cannot be recovered tomorrow.
    #
    # actor_id is a tenant_customer_id or a staff_user_id. NEVER a person_id.
    # A global consumer id here would be the cross-tenant join key, and the
    # warehouse would hold the answer that RLS and the private schema exist to
    # withhold. See ADR 0011.
    op.execute("""
        CREATE TABLE public.event (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id    uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            actor_type   text NOT NULL CHECK (actor_type IN ('staff', 'customer', 'system')),
            actor_id     uuid,
            name         text NOT NULL,
            payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
            occurred_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX event_tenant_time_idx ON public.event (tenant_id, occurred_at DESC);
        CREATE INDEX event_name_idx ON public.event (tenant_id, name, occurred_at DESC);
    """)

    # Append-only. The largest reidentification risk is not a clever tenant; it
    # is one of our own developers with database access.
    op.execute("""
        CREATE TABLE public.audit_log (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id      uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            staff_user_id  uuid REFERENCES public.staff_user(id) ON DELETE SET NULL,
            action         text NOT NULL,
            detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
            occurred_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX audit_log_tenant_time_idx ON public.audit_log (tenant_id, occurred_at DESC);
    """)

    # ------------------------------------------------------------------
    # Row-Level Security.
    #
    # ENABLE alone is not enough: it still exempts the table owner, and Alembic
    # runs as the owner, so the tables belong to it. FORCE is what closes that.
    #
    # Policies fail CLOSED. `current_setting(..., true)` returns NULL when the
    # GUC was never set, and `tenant_id = NULL` is NULL, which matches no rows.
    # The nullif() is required because ''::uuid raises 22P02 rather than
    # returning NULL.
    #
    # WITH CHECK is what stops a tenant from WRITING a row under another
    # tenant's id. USING alone would only protect reads.
    # ------------------------------------------------------------------
    # Policies are scoped TO a role. That matters: a policy with no TO clause
    # applies to PUBLIC, which would silently hand the same rule to app_person
    # and app_platform. Each role gets exactly the policy it needs.
    #
    # Note what this implies for the OWNER: with FORCE and no policy targeting
    # it, the owner sees nothing either. That is intentional. `neondb_owner`
    # migrates the schema; it has no business reading consumer data.
    tenant_tables = [
        "tenant_customer",
        "campaign",
        "campaign_recipient",
        "lead",
        "event",
        "audit_log",
        "staff_user",
    ]
    for table in tenant_tables:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON public.{table} TO app_tenant
              USING      (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
              WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO app_tenant")

    # audit_log is append-only: no UPDATE, no DELETE, not even for the tenant.
    op.execute("REVOKE UPDATE, DELETE ON public.audit_log FROM app_tenant")

    # ---- app_platform: operations that are NOT scoped to a tenant ----
    #
    # Creating a tenant is a platform act, not a tenant act -- there is no
    # `app.tenant_id` yet when the tenant itself is being created. Without this
    # role, onboarding is impossible under FORCE RLS, and the temptation becomes
    # to hand BYPASSRLS to something, which silently kills isolation everywhere.
    #
    # It is deliberately narrow: tenant and staff_user only. It cannot read a
    # single campaign, lead, or consumer.
    op.execute("ALTER TABLE public.tenant ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.tenant FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_platform ON public.tenant TO app_platform
          USING (true) WITH CHECK (true);
        CREATE POLICY staff_platform ON public.staff_user TO app_platform
          USING (true) WITH CHECK (true);
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.tenant TO app_platform")
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.staff_user TO app_platform")

    # ---- app_tenant: may read only its own tenant row ----
    op.execute("""
        CREATE POLICY tenant_self ON public.tenant TO app_tenant
          USING (id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """)
    op.execute("GRANT SELECT ON public.tenant TO app_tenant")

    # ---- app_person: the consumer app ----
    #
    # Stores and their offers are a PUBLIC directory: the consumer browses and
    # follows. That openness is a privacy requirement, not a growth feature --
    # if invitation were the only way in, "has the app" would prove "belongs to
    # some store", and every defense around base import would be theater.
    # See ADR 0005 and threat-model.md §2.
    op.execute("""
        CREATE POLICY tenant_discovery ON public.tenant TO app_person USING (true);
        CREATE POLICY campaign_discovery ON public.campaign TO app_person USING (true);
    """)

    # But the consumer's own relationships are private to them. This is the
    # only place a person_id appears in a policy, and it reads from `private`.
    op.execute("""
        CREATE POLICY customer_own ON public.tenant_customer TO app_person
          USING (
            EXISTS (
              SELECT 1 FROM private.person_link pl
              WHERE pl.tenant_customer_id = public.tenant_customer.id
                AND pl.person_id = nullif(current_setting('app.person_id', true), '')::uuid
            )
          )
          -- Following a store creates the row before the link exists, so INSERT
          -- cannot be checked against the link. The API is responsible for
          -- writing both in one transaction.
          WITH CHECK (true);
    """)
    op.execute("""
        CREATE POLICY lead_own ON public.lead TO app_person
          USING (
            EXISTS (
              SELECT 1 FROM private.person_link pl
              WHERE pl.tenant_customer_id = public.lead.tenant_customer_id
                AND pl.person_id = nullif(current_setting('app.person_id', true), '')::uuid
            )
          )
          WITH CHECK (true);
    """)
    # Consumers emit telemetry; they never read it back.
    op.execute("""
        CREATE POLICY event_write_only ON public.event TO app_person
          USING (false) WITH CHECK (true);
    """)

    op.execute("GRANT SELECT ON public.tenant, public.campaign TO app_person")
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.tenant_customer TO app_person")
    op.execute("GRANT SELECT, INSERT ON public.lead TO app_person")
    op.execute("GRANT INSERT ON public.event TO app_person")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA private TO app_person, app_delivery")
    op.execute("GRANT INSERT, UPDATE, DELETE ON private.device TO app_person")
    op.execute("GRANT INSERT ON private.person, private.person_link TO app_person")

    # ---- app_delivery: the push worker. No HTTP route ever runs as this. ----
    #
    # It is the ONLY role that joins tenant_customer -> person_link -> device,
    # i.e. the only one that can turn "a tenant's customer" back into "a real
    # phone". It must never be handed to the API or to an AI agent worker.
    op.execute("""
        CREATE POLICY recipient_delivery ON public.campaign_recipient TO app_delivery
          USING (true) WITH CHECK (true);
        CREATE POLICY customer_delivery ON public.tenant_customer TO app_delivery
          USING (true);
        CREATE POLICY campaign_delivery ON public.campaign TO app_delivery USING (true);
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE ON public.campaign_recipient TO app_delivery")
    op.execute("GRANT SELECT ON public.tenant_customer, public.campaign TO app_delivery")

    # Deliberately NOT using ALTER DEFAULT PRIVILEGES. It would auto-grant on any
    # future table, including a sensitive one. Explicit GRANTs per migration mean
    # a forgotten grant surfaces as a permission error -- loud, and safe.


def downgrade() -> None:
    for table in [
        "audit_log",
        "event",
        "lead",
        "campaign_recipient",
        "campaign",
        "staff_user",
    ]:
        op.execute(f"DROP TABLE IF EXISTS public.{table} CASCADE")
    op.execute("DROP TABLE IF EXISTS private.person_link CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tenant_customer CASCADE")
    op.execute("DROP TABLE IF EXISTS private.device CASCADE")
    op.execute("DROP TABLE IF EXISTS private.person CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tenant CASCADE")
    op.execute("DROP SCHEMA IF EXISTS private CASCADE")
    # uuidv7() is a Postgres builtin. Nothing to drop -- and dropping it would be
    # actively harmful.
    # Roles are intentionally left in place: dropping a role that owns objects
    # elsewhere fails, and a half-dropped role set is worse than none.
