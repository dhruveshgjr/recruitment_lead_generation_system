from __future__ import annotations

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE TABLE companies (\n\tid SERIAL NOT NULL, \n\tname VARCHAR(300) NOT NULL, \n\tslug VARCHAR(300) NOT NULL, \n\tdomain VARCHAR(255), \n\twebsite VARCHAR(500), \n\thq_city VARCHAR(120), \n\thq_region VARCHAR(120), \n\thq_country VARCHAR(2), \n\theadcount_band VARCHAR(20), \n\topen_roles_band VARCHAR(20), \n\tindustry VARCHAR(120), \n\tnotes TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n);')
    op.execute('CREATE INDEX ix_companies_country_industry ON companies (hq_country, industry);')
    op.execute('CREATE INDEX ix_companies_domain ON companies (domain);')
    op.execute('CREATE INDEX ix_companies_hq_country ON companies (hq_country);')
    op.execute('CREATE INDEX ix_companies_name_search ON companies (name);')
    op.execute('CREATE INDEX ix_companies_open_roles_band ON companies (open_roles_band);')
    op.execute('CREATE UNIQUE INDEX ix_companies_slug ON companies (slug);')
    op.execute('CREATE TABLE recruiters (\n\tid SERIAL NOT NULL, \n\temail VARCHAR(320) NOT NULL, \n\tname VARCHAR(200), \n\tagency VARCHAR(200), \n\tphone VARCHAR(40), \n\tplan VARCHAR(40) NOT NULL, \n\tmonthly_price_cents INTEGER NOT NULL, \n\tis_active BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n);')
    op.execute('CREATE UNIQUE INDEX ix_recruiters_email ON recruiters (email);')
    op.execute('CREATE TABLE job_boards (\n\tid SERIAL NOT NULL, \n\tcompany_id INTEGER NOT NULL, \n\tprovider VARCHAR(40) NOT NULL, \n\ttoken VARCHAR(500) NOT NULL, \n\turl VARCHAR(1000), \n\tis_active BOOLEAN NOT NULL, \n\tlast_started_at TIMESTAMP WITH TIME ZONE, \n\tlast_ok_at TIMESTAMP WITH TIME ZONE, \n\tlast_error TEXT, \n\tconsecutive_failures INTEGER NOT NULL, \n\tlast_job_count INTEGER NOT NULL, \n\tempty_streak INTEGER NOT NULL, \n\tetag VARCHAR(500), \n\tlast_modified VARCHAR(500), \n\tdiscovered_via VARCHAR(40), \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_board_provider_token UNIQUE (provider, token), \n\tFOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE\n);')
    op.execute('CREATE INDEX ix_boards_active_provider ON job_boards (is_active, provider);')
    op.execute('CREATE INDEX ix_job_boards_company_id ON job_boards (company_id);')
    op.execute('CREATE INDEX ix_job_boards_is_active ON job_boards (is_active);')
    op.execute('CREATE INDEX ix_job_boards_provider ON job_boards (provider);')
    op.execute('CREATE TABLE watchlists (\n\tid SERIAL NOT NULL, \n\trecruiter_id INTEGER NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\trole_families VARCHAR[] NOT NULL, \n\tskills VARCHAR[] NOT NULL, \n\texclude_skills VARCHAR[] NOT NULL, \n\tseniorities VARCHAR[] NOT NULL, \n\tcountries VARCHAR[] NOT NULL, \n\tregions VARCHAR[] NOT NULL, \n\tremote_ok BOOLEAN NOT NULL, \n\tmin_score FLOAT NOT NULL, \n\tmax_age_days INTEGER NOT NULL, \n\tdaily_cap INTEGER NOT NULL, \n\tinclude_keywords VARCHAR[] NOT NULL, \n\texclude_keywords VARCHAR[] NOT NULL, \n\tis_active BOOLEAN NOT NULL, \n\temail_enabled BOOLEAN NOT NULL, \n\tlast_delivered_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(recruiter_id) REFERENCES recruiters (id) ON DELETE CASCADE\n);')
    op.execute('CREATE INDEX ix_watchlists_delivery ON watchlists (is_active, email_enabled, last_delivered_at);')
    op.execute('CREATE INDEX ix_watchlists_recruiter_id ON watchlists (recruiter_id);')
    op.execute('CREATE TABLE delivery_runs (\n\tid BIGSERIAL NOT NULL, \n\twatchlist_id INTEGER NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(20) NOT NULL, \n\tlead_count INTEGER NOT NULL, \n\terror TEXT, \n\tmessage_id VARCHAR(300), \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(watchlist_id) REFERENCES watchlists (id) ON DELETE CASCADE\n);')
    op.execute('CREATE INDEX ix_delivery_runs_message_id ON delivery_runs (message_id);')
    op.execute('CREATE INDEX ix_delivery_runs_status ON delivery_runs (status);')
    op.execute('CREATE INDEX ix_delivery_runs_watchlist_id ON delivery_runs (watchlist_id);')
    op.execute('CREATE INDEX ix_delivery_runs_watchlist_started ON delivery_runs (watchlist_id, started_at);')
    op.execute('CREATE TABLE ingestion_runs (\n\tid BIGSERIAL NOT NULL, \n\tboard_id INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tduration_ms INTEGER, \n\tfetched INTEGER NOT NULL, \n\tcreated INTEGER NOT NULL, \n\tupdated INTEGER NOT NULL, \n\tdeduped INTEGER NOT NULL, \n\tdeactivated INTEGER NOT NULL, \n\terror TEXT, \n\tmetadata_json JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(board_id) REFERENCES job_boards (id) ON DELETE CASCADE\n);')
    op.execute('CREATE INDEX ix_ingestion_runs_board_id ON ingestion_runs (board_id);')
    op.execute('CREATE INDEX ix_ingestion_runs_board_started ON ingestion_runs (board_id, started_at);')
    op.execute('CREATE INDEX ix_ingestion_runs_status ON ingestion_runs (status);')
    op.execute('CREATE TABLE job_postings (\n\tid BIGSERIAL NOT NULL, \n\tboard_id INTEGER NOT NULL, \n\tcompany_id INTEGER NOT NULL, \n\texternal_id VARCHAR(200) NOT NULL, \n\ttitle VARCHAR(400) NOT NULL, \n\tnormalized_title VARCHAR(400) NOT NULL, \n\tdescription TEXT, \n\tdepartment VARCHAR(200), \n\temployment_type VARCHAR(60), \n\tseniority VARCHAR(20), \n\trole_family VARCHAR(40), \n\trole_family_confidence FLOAT NOT NULL, \n\tclassification_evidence VARCHAR[] NOT NULL, \n\tskills VARCHAR[] NOT NULL, \n\tlocation_raw VARCHAR(300), \n\tcity VARCHAR(120), \n\tregion VARCHAR(120), \n\tcountry VARCHAR(2), \n\tremote_type VARCHAR(12), \n\tsalary_min FLOAT, \n\tsalary_max FLOAT, \n\tsalary_currency VARCHAR(3), \n\turl VARCHAR(1000) NOT NULL, \n\tapply_url VARCHAR(1000), \n\tposted_at TIMESTAMP WITH TIME ZONE, \n\tupdated_at_source TIMESTAMP WITH TIME ZONE, \n\tfirst_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tmissed_scans INTEGER NOT NULL, \n\tis_active BOOLEAN NOT NULL, \n\tis_bulk_import BOOLEAN NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tdedupe_key VARCHAR(64) NOT NULL, \n\tdedupe_bucket VARCHAR(100) NOT NULL, \n\trepost_of_id BIGINT, \n\traw JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_posting_board_external UNIQUE (board_id, external_id), \n\tCONSTRAINT ck_posting_salary_order CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max), \n\tFOREIGN KEY(board_id) REFERENCES job_boards (id) ON DELETE CASCADE, \n\tFOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, \n\tFOREIGN KEY(repost_of_id) REFERENCES job_postings (id) ON DELETE SET NULL\n);')
    op.execute('CREATE INDEX ix_job_postings_board_id ON job_postings (board_id);')
    op.execute('CREATE INDEX ix_job_postings_company_id ON job_postings (company_id);')
    op.execute('CREATE INDEX ix_job_postings_content_hash ON job_postings (content_hash);')
    op.execute('CREATE INDEX ix_job_postings_country ON job_postings (country);')
    op.execute('CREATE INDEX ix_job_postings_dedupe_bucket ON job_postings (dedupe_bucket);')
    op.execute('CREATE INDEX ix_job_postings_dedupe_key ON job_postings (dedupe_key);')
    op.execute('CREATE INDEX ix_job_postings_first_seen_at ON job_postings (first_seen_at);')
    op.execute('CREATE INDEX ix_job_postings_is_active ON job_postings (is_active);')
    op.execute('CREATE INDEX ix_job_postings_is_bulk_import ON job_postings (is_bulk_import);')
    op.execute('CREATE INDEX ix_job_postings_last_seen_at ON job_postings (last_seen_at);')
    op.execute('CREATE INDEX ix_job_postings_normalized_title ON job_postings (normalized_title);')
    op.execute('CREATE INDEX ix_job_postings_posted_at ON job_postings (posted_at);')
    op.execute('CREATE INDEX ix_job_postings_remote_type ON job_postings (remote_type);')
    op.execute('CREATE INDEX ix_job_postings_role_family ON job_postings (role_family);')
    op.execute('CREATE INDEX ix_job_postings_seniority ON job_postings (seniority);')
    op.execute('CREATE INDEX ix_postings_active_first_seen ON job_postings (is_active, first_seen_at);')
    op.execute('CREATE INDEX ix_postings_bucket_recent ON job_postings (dedupe_bucket, last_seen_at);')
    op.execute('CREATE INDEX ix_postings_company_active ON job_postings (company_id, is_active);')
    op.execute('CREATE INDEX ix_postings_family_first_seen ON job_postings (role_family, first_seen_at);')
    op.execute('CREATE TABLE classification_reviews (\n\tid BIGSERIAL NOT NULL, \n\tjob_id BIGINT NOT NULL, \n\tpredicted_family VARCHAR(40), \n\tconfidence FLOAT NOT NULL, \n\tevidence VARCHAR[] NOT NULL, \n\tcorrected_family VARCHAR(40), \n\treviewed_at TIMESTAMP WITH TIME ZONE, \n\treviewer_note TEXT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_classification_review_job UNIQUE (job_id), \n\tFOREIGN KEY(job_id) REFERENCES job_postings (id) ON DELETE CASCADE\n);')
    op.execute('CREATE INDEX ix_classification_review_pending ON classification_reviews (reviewed_at, confidence);')
    op.execute('CREATE INDEX ix_classification_reviews_job_id ON classification_reviews (job_id);')
    op.execute('CREATE TABLE delivered_leads (\n\tid BIGSERIAL NOT NULL, \n\twatchlist_id INTEGER NOT NULL, \n\tjob_id BIGINT NOT NULL, \n\tscore FLOAT NOT NULL, \n\tdelivered_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_delivered_wl_job UNIQUE (watchlist_id, job_id), \n\tFOREIGN KEY(watchlist_id) REFERENCES watchlists (id) ON DELETE CASCADE, \n\tFOREIGN KEY(job_id) REFERENCES job_postings (id) ON DELETE CASCADE\n);')
    op.execute('CREATE INDEX ix_delivered_leads_job_id ON delivered_leads (job_id);')
    op.execute('CREATE INDEX ix_delivered_leads_watchlist_id ON delivered_leads (watchlist_id);')
    op.execute('CREATE INDEX ix_delivered_watchlist_time ON delivered_leads (watchlist_id, delivered_at);')

def downgrade() -> None:
    for table in (
        "classification_reviews",
        "delivered_leads",
        "job_postings",
        "ingestion_runs",
        "delivery_runs",
        "watchlists",
        "job_boards",
        "recruiters",
        "companies",
    ):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
