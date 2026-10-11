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

