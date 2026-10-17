The output shows exactly why the installer is failing: nixos-generate-config did not scan your hard drive partitions. Instead, it accidentally scanned your live USB installer environment because the actual installation drive partitions are not correctly mounted under /mnt.
Look at your current file systems: your root filesystem (/) is listed as tmpfs (RAM) instead of your hard drive, your boot partition is mapped to /mnt/boot instead of /boot, and it is referencing the /iso squashfs image. If you run nixos-install with this layout, it will erase itself from RAM upon reboot.
Here is how to properly mount your physical disk partitions and fix your layout before finalizing the install.
## Step 1: Re-mount Your Real Hard Drive Partitions
We need to ensure your physical hard drive partitions are mounted correctly to /mnt.

   1. Run lsblk to view your actual partitions. Identify your main Linux system partition (e.g., /dev/nvme0n1p2 or /dev/sda2, usually formatted as ext4, btrfs, or zfs) and your EFI boot partition (e.g., /dev/nvme0n1p1 or /dev/sda1, formatted as vfat).
   2. Unmount the incorrect paths from your current session:
   
   sudo umount /mnt/boot 2>/dev/null
   sudo umount -R /mnt 2>/dev/null
   
   3. Mount your real Linux system partition to /mnt (replace /dev/nvme0n1p2 with your actual Linux partition):
   
   sudo mount /dev/nvme0n1p2 /mnt
   
   4. Create the correct boot directory and mount your real EFI boot partition to it (replace /dev/nvme0n1p1 with your actual EFI partition):
   
   sudo mkdir -p /mnt/boot
   sudo mount /dev/nvme0n1p1 /mnt/boot
   
   
## Step 2: Regenerate the Hardware Map
Now that the real physical disks are sitting underneath /mnt, the generator will scan your storage controllers and partition UUIDs perfectly.

   1. Force a clean generation matching your physical hard drive structure:
   
   sudo nixos-generate-config --root /mnt
   
   2. Verify that it worked by viewing the file:
   
   cat /mnt/etc/nixos/hardware-configuration.nix
   
   Your fileSystems."/" block should now display an actual physical drive UUID with a type like ext4 or btrfs, and fileSystems."/boot" should show your EFI drive path.

## Step 3: Sync and Stage with Git
Because you wiped out the configuration directories under /mnt during re-mounting, make sure your customized configuration.nix and flake.nix are present in /mnt/etc/nixos/. If they were lost during the unmount process, re-copy them from your cloning phase or modify them quickly to match what we fixed earlier.
Once your files are verified inside /mnt/etc/nixos/, track them with Git:

cd /mnt/etc/nixos
sudo git init
sudo git add hardware-configuration.nix configuration.nix flake.nix

## Step 4: Finalize the Installation
Run the installer script:

sudo nixos-install --flake /mnt/etc/nixos#beast-kf

If nixos-generate-config still outputs tmpfs blocks or if you are unsure which partition targets are correct, please run lsblk and paste the layout here. I can tell you exactly which partitions to mount.

---

This NAR hash mismatch error happens because the Nix evaluation cache got confused when files were rapidly modified, staged, or remounted directly inside /mnt/etc/nixos. Because Nix flakes track files strictly by cryptographic content hashes, any out-of-sync evaluation metadata halts the installer instantly.
The issue can be resolved by clearing the temporary evaluation locks and committing your configuration files directly to clear the caching layer.
## Step-by-Step Fix
Run these commands sequentially inside your installer terminal to reset the state:

# 1. Change directories into your configuration root
cd /mnt/etc/nixos
# 2. Obliterate the out-of-sync flake lockfile and cache references
sudo rm -f flake.lock
# 3. Inform Git of your identity (required to safely make a local commit)
sudo git config --global user.email "installer@nixos.org"
sudo git config --global user.name "NixOS Installer"
# 4. Stage and record a local commit to lock down the exact file state
sudo git add -A
sudo git commit -m "install: freeze state to prevent NAR hash mismatch"

## Step 2: Complete the Installation
Now that the file tree is cleanly indexed by Git and the old cache is wiped, run the installer one more time:

sudo nixos-install --flake /mnt/etc/nixos#beast-kf

Nix will cleanly re-generate a precise lockfile matching your configurations and complete the setup.
Once the installation finishes, it will prompt you for user passwords. Let me know:

* If it displays a "system installation finished!" success verification message.
* When you want the proper step-by-step commands to safely unmount your drives and reboot into GNOME for the first time.

---


why there is need for git?


The requirement for Git comes down to how NixOS Flakes work under the hood.
When you run nixos-install --flake /mnt/etc/nixos#beast-kf, Nix looks inside that directory and checks if a .git folder exists. If Git is present, Nix activates Strict Reproducibility Mode. This design choice imposes three critical behaviors:
## 1. The "If It's Not Staged, It Doesn't Exist" Rule
To guarantee that a configuration can be exactly reproduced anywhere, Nix flakes will completely ignore any file not explicitly tracked by Git.

* When you ran nixos-generate-config, it created hardware-configuration.nix.
* Because that file was new and untracked, Nix acted as if it was completely missing, throwing the error that your root filesystem wasn't specified.
* Running git add forces Nix to acknowledge the file's contents.

## 2. Preventing "Dirty State" Contradictions
Nix takes a cryptographic snapshot (the NAR hash) of your directory to build your system. If you edit files or generate logs while Nix is mid-build, the folder contents change, the hashes mismatch, and Nix throws the exact NAR hash mismatch error you saw. Committing the files locks them into a static state, allowing the build to proceed safely.
## 3. Absolute Version Control Over Hardware
The ultimate goal of NixOS is to allow you to back up your entire operating system as code. By forcing your configurations into Git, you can push your changes straight to [GitHub](https://github.com/). If a system update ever breaks your computer, you can look at your Git history, see exactly what changed, and roll back down to the exact block of code.
Did the commit fix clear out the hash mismatch and let your installation finalize successfully? Let me know if you are ready for the reboot steps!

---

IMPORTANT !!!! - this is the way to clone, and git is important for the flake !!!

[nixos@nixos:/mnt/etc/nixos]$ sudo git clone  https://github.com/romancerny/nixos-DeepSeek-R1-Distill-Llama-70B-Quantized.git .


