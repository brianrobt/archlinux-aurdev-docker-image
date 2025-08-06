# Use the official Arch Linux base image
FROM archlinux/archlinux:latest

# Set build arguments for cross-platform compatibility
ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG TARGETARCH
ARG TARGETOS



# Update the system and install packages in a single RUN command to reduce layers
RUN pacman -Syu --noconfirm && \
    pacman -Sy archlinux-keyring --noconfirm && \
    pacman -Su --noconfirm && \
    pacman -S --noconfirm \
    git \
    sudo \
    base-devel \
    vim \
    cmake \
    ninja \
    python-pip \
    pacman-contrib \
    wget && \
    pacman -Scc --noconfirm

# Create a non-root user for building packages
RUN useradd -m -G wheel builder && \
    echo "builder ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers && \
    chown -R builder:builder /home/builder

# Switch to the builder user
USER builder
WORKDIR /home/builder

# Install yay (AUR helper)
RUN git clone https://aur.archlinux.org/yay.git && \
    cd yay && \
    makepkg -si --noconfirm --skippgpcheck && \
    cd .. && \
    rm -rf yay

RUN yay -S --noconfirm \
    devtools \
    rust \
    namcap \
    paru \
    python-pip \
    tree \
    treeify
