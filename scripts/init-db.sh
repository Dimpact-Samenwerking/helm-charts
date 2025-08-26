#!/bin/bash

# Database initialization script for ITA
# This script checks if the "ita" database and user exist in PostgreSQL 
# and creates them if they don't exist

set -e

# Configuration
DB_HOST="${DB_HOST:-ita-postgresql}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-ita}"
DB_USER="${DB_USER:-ita}"
DB_PASSWORD="${DB_PASSWORD:-@Th1sIsASecret@}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-@Th1sIsASecret@}"

echo "🔍 Checking if database '${DB_NAME}' and user '${DB_USER}' exist..."

# Function to check if database exists
check_database_exists() {
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
        -U "${POSTGRES_USER}" -d "postgres" -t \
        -c "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}';" \
        2>/dev/null | grep -q 1
}

# Function to create database
create_database() {
    echo "🗄️  Creating database '${DB_NAME}'..."
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
        -U "${POSTGRES_USER}" -d "postgres" \
        -c "CREATE DATABASE ${DB_NAME};"
    echo "✅ Database '${DB_NAME}' created successfully!"
}

# Function to check if user exists
check_user_exists() {
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
        -U "${POSTGRES_USER}" -d "postgres" -t \
        -c "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}';" \
        2>/dev/null | grep -q 1
}

# Function to create user
create_user() {
    echo "👤 Creating user '${DB_USER}'..."
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
        -U "${POSTGRES_USER}" -d "postgres" \
        -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
    echo "✅ User '${DB_USER}' created successfully!"
}

# Function to grant privileges
grant_privileges() {
    echo "🔐 Granting privileges to user '${DB_USER}'..."
    
    # Execute SQL commands using heredoc to avoid long lines
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
        -U "${POSTGRES_USER}" -d "${DB_NAME}" << EOF
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
GRANT USAGE ON SCHEMA public TO ${DB_USER};
GRANT CREATE ON SCHEMA public TO ${DB_USER};
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_USER};
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO ${DB_USER};
EOF
    
    echo "✅ Privileges granted successfully!"
}

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
until PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" \
    -U "${POSTGRES_USER}" -d "postgres" -c '\q' 2>/dev/null; do
    echo "📡 PostgreSQL is not ready yet, waiting..."
    sleep 2
done
echo "✅ PostgreSQL is ready!"

# Check if database exists
if check_database_exists; then
    echo "✅ Database '${DB_NAME}' already exists!"
else
    echo "❌ Database '${DB_NAME}' does not exist, creating..."
    create_database
fi

# Check if user exists
if check_user_exists; then
    echo "✅ User '${DB_USER}' already exists!"
    echo "🔐 Granting privileges to existing user..."
    grant_privileges
else
    echo "❌ User '${DB_USER}' does not exist, creating..."
    create_user
    grant_privileges
fi

echo "🎉 Database initialization completed successfully!"
