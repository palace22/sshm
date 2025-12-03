#!/bin/bash

# SSH Manager Installation Script
# This script provides multiple ways to install sshm

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to detect Python version
get_python_version() {
    if command_exists python3; then
        python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    elif command_exists python; then
        python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    else
        echo "0.0"
    fi
}

# Function to check Python version compatibility
check_python_version() {
    local version=$(get_python_version)
    local major=$(echo $version | cut -d. -f1)
    local minor=$(echo $version | cut -d. -f2)

    if [[ $major -lt 3 ]] || [[ $major -eq 3 && $minor -lt 10 ]]; then
        print_error "Python 3.10 or higher is required. Found: $version"
        return 1
    fi

    print_info "Python version $version detected - compatible!"
    return 0
}

# Function to install via pip from GitHub
install_from_github() {
    print_info "Installing sshm from GitHub repository..."

    if command_exists pip3; then
        pip3 install --user git+https://github.com/palace22/sshm.git
    elif command_exists pip; then
        pip install --user git+https://github.com/palace22/sshm.git
    else
        print_error "pip not found. Please install pip first."
        return 1
    fi
}

# Function to install for development
install_dev() {
    print_info "Installing sshm for development..."

    # Clone repository if not already present
    if [[ ! -d "sshm" ]]; then
        print_info "Cloning repository..."
        git clone https://github.com/palace22/sshm.git
        cd sshm
    fi

    if command_exists poetry; then
        poetry install --with dev
        print_info "Development dependencies installed via Poetry"
    else
        print_info "Installing via pip with development dependencies..."
        if command_exists pip3; then
            pip3 install --user -e ".[dev]"
        elif command_exists pip; then
            pip install --user -e ".[dev]"
        else
            print_error "pip not found. Please install pip first."
            return 1
        fi
    fi
}

# Function to setup PATH
setup_path() {
    local shell_config=""

    # Detect shell and config file
    if [[ $SHELL == *"zsh"* ]]; then
        shell_config="$HOME/.zshrc"
    elif [[ $SHELL == *"bash"* ]]; then
        shell_config="$HOME/.bashrc"
    else
        print_warning "Unable to detect shell. You may need to manually add ~/.local/bin to your PATH"
        return 0
    fi

    # Check if PATH is already configured
    if grep -q 'export PATH="$PATH:$HOME/.local/bin"' "$shell_config" 2>/dev/null; then
        print_info "PATH already configured in $shell_config"
        return 0
    fi

    print_info "Adding ~/.local/bin to PATH in $shell_config"
    echo 'export PATH="$PATH:$HOME/.local/bin"' >> "$shell_config"
    print_warning "Please restart your shell or run: source $shell_config"
}

# Function to verify installation
verify_installation() {
    print_info "Verifying installation..."

    if command_exists sshm; then
        print_success "sshm command is available!"
        sshm --help | head -3
        return 0
    else
        print_warning "sshm command not found in PATH"
        print_info "Checking if installed in ~/.local/bin..."

        if [[ -f "$HOME/.local/bin/sshm" ]]; then
            print_info "Found sshm in ~/.local/bin"
            print_info "Please add ~/.local/bin to your PATH or restart your shell"
            return 0
        else
            print_error "Installation verification failed"
            return 1
        fi
    fi
}

# Main installation function
main() {
    print_info "SSH Manager (sshm) Installation Script"
    print_info "======================================"

    # Check Python version
    if ! check_python_version; then
        exit 1
    fi

    # Parse command line arguments
    case "${1:-auto}" in
        "github"|"auto"|*)
            install_from_github
            ;;
        "dev")
            install_dev
            ;;
    esac

    # Setup PATH
    setup_path

    # Verify installation
    if verify_installation; then
        print_success "Installation completed successfully!"
        print_info ""
        print_info "Quick start:"
        print_info "  sshm list          # List all connections"
        print_info "  sshm add           # Add a new connection"
        print_info "  sshm connect NAME  # Connect to a host"
        print_info ""
        print_info "For more help: sshm --help"
    else
        print_error "Installation completed but verification failed"
        exit 1
    fi
}

# Show usage if --help is passed
if [[ "${1}" == "--help" ]] || [[ "${1}" == "-h" ]]; then
    echo "SSH Manager Installation Script"
    echo ""
    echo "Usage: $0 [METHOD]"
    echo ""
    echo "Methods:"
    echo "  auto    - Install from GitHub repository (default)"
    echo "  github  - Install from GitHub repository"
    echo "  dev     - Install for development"
    echo ""
    echo "Examples:"
    echo "  $0              # Auto-install from GitHub"
    echo "  $0 github       # Install from GitHub"
    echo "  $0 dev          # Development installation"
    exit 0
fi

# Run main function
main "$@"
