#!/bin/bash
# =============================================================================
# ec2-setup.sh — One-shot setup script for Ubuntu EC2 (t2.micro / t3.micro)
#
# Run this ONCE on a fresh EC2 instance:
#   curl -fsSL https://raw.githubusercontent.com/vobiz-ai/Vobiz-All-XML/main/ec2-setup.sh | bash
#
# Or copy it to the instance and run:
#   chmod +x ec2-setup.sh && ./ec2-setup.sh
# =============================================================================

set -e

echo ""
echo "=========================================="
echo "  Vobiz Voice Agent — EC2 Setup"
echo "=========================================="
echo ""

# ---------------------------------------------------------------------------
# 1. System update
# ---------------------------------------------------------------------------
echo "[1/6] Updating system packages..."
sudo apt-get update -y && sudo apt-get upgrade -y

# ---------------------------------------------------------------------------
# 2. Install Docker
# ---------------------------------------------------------------------------
echo "[2/6] Installing Docker..."
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow running docker without sudo
sudo usermod -aG docker $USER

echo "[2/6] Docker installed: $(docker --version)"

# ---------------------------------------------------------------------------
# 3. Install Docker Compose (standalone)
# ---------------------------------------------------------------------------
echo "[3/6] Installing Docker Compose..."
COMPOSE_VERSION="v2.24.5"
sudo curl -SL \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
echo "[3/6] Docker Compose installed: $(docker-compose --version)"

# ---------------------------------------------------------------------------
# 4. Clone the repo
# ---------------------------------------------------------------------------
echo "[4/6] Cloning Vobiz Voice Agent repo..."
cd /home/ubuntu

if [ -d "Vobiz-All-XML" ]; then
    echo "  Repo already exists — pulling latest..."
    cd Vobiz-All-XML && git pull
else
    git clone https://github.com/vobiz-ai/Vobiz-All-XML.git
    cd Vobiz-All-XML
fi

# ---------------------------------------------------------------------------
# 5. Create .env from example
# ---------------------------------------------------------------------------
echo "[5/6] Setting up .env file..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  *** .env created from .env.example ***"
    echo "  You MUST edit it before starting:"
    echo ""
    echo "    nano /home/ubuntu/Vobiz-All-XML/.env"
    echo ""
    echo "  Required values to fill in:"
    echo "    OPENAI_API_KEY=..."
    echo "    DEEPGRAM_API_KEY=..."
    echo "    VOBIZ_AUTH_ID=..."
    echo "    VOBIZ_AUTH_TOKEN=..."
    echo "    FROM_NUMBER=+91XXXXXXXXXX"
    echo "    TO_NUMBER=+91XXXXXXXXXX"
    echo "    PUBLIC_URL=https://<your-ec2-public-dns>"
    echo ""
else
    echo "  .env already exists — skipping."
fi

# ---------------------------------------------------------------------------
# 6. Configure EC2 Security Group reminder
# ---------------------------------------------------------------------------
echo "[6/6] Setup complete!"
echo ""
echo "=========================================="
echo "  NEXT STEPS"
echo "=========================================="
echo ""
echo "1. Edit your .env file:"
echo "   nano /home/ubuntu/Vobiz-All-XML/.env"
echo ""
echo "2. Set PUBLIC_URL to your EC2 public DNS:"
echo "   PUBLIC_URL=https://$(curl -s http://169.254.169.254/latest/meta-data/public-hostname 2>/dev/null || echo '<your-ec2-public-dns>')"
echo ""
echo "3. Make sure port 8000 is open in your EC2 Security Group:"
echo "   AWS Console → EC2 → Security Groups → Inbound Rules → Add:"
echo "   Type: Custom TCP | Port: 8000 | Source: 0.0.0.0/0"
echo ""
echo "4. Start the agent:"
echo "   cd /home/ubuntu/Vobiz-All-XML"
echo "   sudo newgrp docker  # or log out and back in"
echo "   docker-compose up -d"
echo ""
echo "5. Check it's running:"
echo "   docker-compose logs -f"
echo "   curl http://localhost:8000/health"
echo ""
echo "6. Set in Vobiz Console:"
echo "   Answer URL: https://<your-ec2-dns>:8000/answer"
echo "   SIP URI:    https://<your-ec2-dns>:8000/sip"
echo ""
echo "=========================================="
