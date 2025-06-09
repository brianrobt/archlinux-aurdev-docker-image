# Use the official Arch Linux base image
# FROM --platform=linux/arm64 archlinux/archlinux:latest for new Macs
FROM archlinux/archlinux:latest

# Update the system and install git (needed for some AUR helpers)
RUN pacman -Syu --noconfirm && \
    pacman -S --noconfirm \
    git \
    sudo \
    base-devel \
    vim \
    cmake \
    ninja \
    python-pip

# Create a non-root user for building packages
RUN useradd -m -G wheel builder && \
    echo "builder ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Switch to the builder user
USER builder
WORKDIR /home/builder

# Install yay (AUR helper)
RUN git clone https://aur.archlinux.org/yay.git && \
    cd yay && \
    makepkg -si --noconfirm && \
    cd .. && \
    rm -rf yay

RUN yay -S --noconfirm \
    devtools \
    rust \
    paru \
    python-pip \
    tree \
    treeify