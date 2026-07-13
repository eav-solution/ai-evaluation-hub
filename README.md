# AI Evaluation Hub

AI Evaluation Hub helps teams evaluate model answers, RAG pipelines, and live API endpoints with repeatable datasets, metrics, reports, and provider connections.

For product workflows—creating a workspace, connecting a provider, uploading a dataset, launching a run, and reading reports—see the [User Guide](docs/user-guide/user-guide.md).

## Run locally

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Docker Compose.
- The ports `3000`, `5432`, `6379`, `8000`, `9000`, and `9001` available on your machine.

### 1. Create local configuration

Copy the example configuration. The resulting `.env` file is ignored by Git and must not be committed.

```sh
cp .env.example .env
```

Create a Fernet key. This encrypts provider API keys and live-endpoint headers before they are stored.

```sh
docker compose build api
docker compose run --rm --no-deps api python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the printed value into `.env` as `FERNET_KEY=<printed-value>`. Also replace the example `JWT_SECRET` with a private random value, for example:

```sh
openssl rand -hex 32
```

### 2. Start the application

```sh
docker compose up --build -d
```

The first start builds the frontend and backend images, runs database migrations, then starts the web app, API, worker, scheduler, PostgreSQL, Redis, and MinIO.

Open [http://localhost:3000](http://localhost:3000), create an account, and follow the [Quick Start](docs/user-guide/user-guide.md#quick-start).

Useful local addresses:

| Service | Address |
| --- | --- |
| Web app | [http://localhost:3000](http://localhost:3000) |
| API health check | [http://localhost:8000/api/health](http://localhost:8000/api/health) |
| MinIO console | [http://localhost:9001](http://localhost:9001) |

To stop the local stack, press `Ctrl+C`, or run:

```sh
docker compose down
```

Use `docker compose down -v` only when you also want to remove local database and object-storage data.

## Verification

Backend tests need a separate `evalhub_test` database. With the local stack running, create it once:

```sh
docker compose exec postgres psql -U postgres -c "CREATE DATABASE evalhub_test"
```

Then run the checks in temporary containers:

```sh
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/evalhub_test \
  api python -m pytest
docker compose run --rm --no-deps web npm test
docker compose run --rm --no-deps -v /app/.next web npm run build
```

The anonymous `/app/.next` volume keeps the production build output separate from the active development server's cache.
