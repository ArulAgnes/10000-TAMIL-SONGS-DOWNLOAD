#!/bin/bash

# Audio Collection Analyzer Setup Script

set -e

echo "========================================"
echo "Audio Collection Analyzer Setup"
echo "========================================"
echo ""

# Check prerequisites
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "❌ $1 is not installed"
        return 1
    else
        echo "✓ $1 is installed"
        return 0
    fi
}

echo "Checking prerequisites..."
check_command "docker" || exit 1
check_command "docker-compose" || exit 1
check_command "node" || exit 1
check_command "npm" || exit 1
check_command "python3" || exit 1
echo ""

# Create directories
echo "Creating directories..."
mkdir -p downloads archives temp logs
echo "✓ Directories created"
echo ""

# Setup backend
echo "Setting up backend..."
cd backend

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "✓ Backend setup complete"
echo ""

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating backend .env file..."
    cp .env.example .env
    echo "✓ Backend .env created (please review and update)"
fi

cd ..

# Setup frontend
echo "Setting up frontend..."
cd frontend

# Install dependencies
echo "Installing Node.js dependencies..."
npm install

echo "✓ Frontend setup complete"
echo ""

# Create .env.local if it doesn't exist
if [ ! -f ".env.local" ]; then
    echo "Creating frontend .env.local file..."
    cp .env.example .env.local
    echo "✓ Frontend .env.local created"
fi

cd ..

# Setup root .env
echo "Setting up root environment..."
if [ ! -f ".env" ]; then
    echo "DATABASE_URL=postgresql://postgres:${DATABASE_URL}@127.0.0.1:5432/app_db
NEXT_PUBLIC_API_URL=http://localhost:8000" > .env
    echo "✓ Root .env created"
fi

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Start the database (using Docker):"
echo "   docker-compose up -d db"
echo ""
echo "2. Start the backend (in one terminal):"
echo "   cd backend"
echo "   source venv/bin/activate"
echo "   python -m app.main"
echo ""
echo "3. Start the frontend (in another terminal):"
echo "   npm run dev"
echo ""
echo "4. Open http://localhost:3000 in your browser"
echo ""
echo "Or use Docker Compose to start everything:"
echo "   docker-compose up -d"
echo ""
