import os
from playwright.sync_api import sync_playwright

def launch_spotify_with_profile():
    # 1. Paths for Brave Browser executable on Windows
    possible_brave_paths = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    
    brave_path = None
    for path in possible_brave_paths:
        if os.path.exists(path):
            brave_path = path
            break
            
    if not brave_path:
        raise FileNotFoundError(
            "Brave browser executable not found. Please ensure Brave is installed, "
            "or manually update the executable path in the script."
        )

    # 2. Path to local Brave User Data directory
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ["USERPROFILE"], r"AppData\Local")
    user_data_dir = os.path.join(local_appdata, r"BraveSoftware\Brave-Browser\User Data")
    
    # 3. Specify the default profile name for Brave
    profile_name = "Default"
    
    print(f"Opening Brave profile '{profile_name}' using: {brave_path}")
    print(f"User Data directory: {user_data_dir}")
    print("IMPORTANT: Ensure all instances of Brave Browser are closed before running this script.")

    with sync_playwright() as p:
        # Launch using actual persistent local profile data
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=brave_path,
            headless=False,  # Set to True if you want it to run in the background
            args=[
                "--no-first-run",
                f"--profile-directory={profile_name}"
            ]
        )
        
        # Open a page and navigate to Spotify
        page = context.new_page()
        page.goto("https://open.spotify.com")
        
        print("Spotify opened. Keeping the browser open...")
        
        # This keeps the script running so the browser doesn't instantly close.
        # Press Ctrl+C in your terminal when you want to end the script.
        try:
            page.wait_for_timeout(999999)
        except KeyboardInterrupt:
            print("\nClosing browser context.")
        finally:
            context.close()

if __name__ == "__main__":
    launch_spotify_with_profile()