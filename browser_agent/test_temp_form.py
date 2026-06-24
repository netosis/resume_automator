import os
import math
import random
import time
import sys

try:
    import pyautogui
except ImportError:
    print("Error: The 'pyautogui' library is not installed.")
    print("Please install it using: pip install pyautogui")
    sys.exit(1)

from browser_tools import PersistentBrowserManager

# PyAutoGUI safety settings
# FAILSAFE = True means if you drag your mouse to a corner of the screen, it will abort the script
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

def human_mouse_move_pyautogui(end_x, end_y):
    """
    Moves the OS mouse cursor to (end_x, end_y) using a Cubic Bezier Curve 
    combined with high-frequency jitter (Perlin noise proxy) to simulate human movement.
    """
    start_x, start_y = pyautogui.position()
    
    # Calculate distance
    dx = end_x - start_x
    dy = end_y - start_y
    dist = math.hypot(dx, dy)
    
    # If already close, just move there directly
    if dist < 5:
        pyautogui.moveTo(end_x, end_y)
        return

    # Randomize steps based on distance
    steps = max(20, min(100, int(dist / 8)))

    # Two intermediate control points for a cubic bezier curve
    p0 = (start_x, start_y)
    p3 = (end_x, end_y)
    
    # Random arc direction and magnitude to make a natural curved swoop
    arc_magnitude = random.uniform(0.1, 0.3) * dist
    arc_direction = 1 if random.random() > 0.5 else -1
    
    # Vector perpendicular to trajectory
    perp_x = -dy / dist * arc_magnitude * arc_direction
    perp_y = dx / dist * arc_magnitude * arc_direction
    
    # Control point 1 (around 30% of the way) + random deviation
    p1 = (
        start_x + dx * 0.3 + perp_x + random.uniform(-dist*0.1, dist*0.1),
        start_y + dy * 0.3 + perp_y + random.uniform(-dist*0.1, dist*0.1)
    )
    
    # Control point 2 (around 70% of the way) + random deviation
    p2 = (
        start_x + dx * 0.7 + perp_x * random.uniform(0.5, 1.5) + random.uniform(-dist*0.1, dist*0.1),
        start_y + dy * 0.7 + perp_y * random.uniform(0.5, 1.5) + random.uniform(-dist*0.1, dist*0.1)
    )

    for i in range(1, steps + 1):
        t = i / steps
        # Apply easing to slow down at the start and end (EaseInOutSine)
        t_eased = -(math.cos(math.pi * t) - 1) / 2
        
        # Cubic Bezier formula
        u = 1 - t_eased
        x = (u**3 * p0[0] + 
             3 * u**2 * t_eased * p1[0] + 
             3 * u * t_eased**2 * p2[0] + 
             t_eased**3 * p3[0])
        
        y = (u**3 * p0[1] + 
             3 * u**2 * t_eased * p1[1] + 
             3 * u * t_eased**2 * p2[1] + 
             t_eased**3 * p3[1])
        
        # Add high-frequency jitter (proxy for perlin noise / hand tremors)
        # Jitter is higher in the middle of movement and lower near the start/end
        jitter_factor = math.sin(math.pi * t)
        jitter_x = random.uniform(-2, 2) * jitter_factor
        jitter_y = random.uniform(-2, 2) * jitter_factor
        
        target_x = int(x + jitter_x)
        target_y = int(y + jitter_y)
        
        # Move PyAutoGUI cursor
        pyautogui.moveTo(target_x, target_y)
        
        # Variable time sleep to simulate human inconsistency
        time.sleep(random.uniform(0.005, 0.015))
        
    # Ensure it lands exactly on target
    pyautogui.moveTo(end_x, end_y)

def get_element_screen_coordinates(page, selector):
    """
    Evaluates JavaScript to map the element's relative viewport bounding box 
    to absolute monitor screen coordinates so PyAutoGUI can click it.
    """
    coords = page.evaluate(f"""() => {{
        const el = document.querySelector("{selector}");
        if (!el) return null;
        const rect = el.getBoundingClientRect();
        
        // Approximate the browser's top UI height (tabs, address bar)
        const chromeTopHeight = window.outerHeight - window.innerHeight;
        // Approximate side borders
        const borderLeftWidth = (window.outerWidth - window.innerWidth) / 2;
        
        // Calculate absolute screen position of the center of the element
        const absoluteX = window.screenX + borderLeftWidth + rect.left + (rect.width / 2);
        const absoluteY = window.screenY + chromeTopHeight + rect.top + (rect.height / 2);
        
        return [absoluteX, absoluteY];
    }}""")
    return coords

def human_type_pyautogui(text):
    """
    Types text using PyAutoGUI with human-like randomized delays.
    """
    for char in text:
        pyautogui.write(char)
        time.sleep(random.uniform(0.03, 0.1))

def main():
    print("Initializing Persistent Browser Manager...")
    manager = PersistentBrowserManager.get_instance()
    page = manager.get_page()

    # Create a Temporary Form HTML File
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Temporary Test Form (PyAutoGUI)</title>
        <style>
            body { font-family: sans-serif; margin: 40px; background-color: #f9f9f9; }
            .form-container { 
                border: 1px solid #ccc; padding: 25px; width: 350px; 
                border-radius: 8px; background-color: white;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            label { font-weight: bold; margin-top: 10px; display: block; }
            input[type="text"], input[type="email"] { 
                width: 100%; padding: 10px; margin: 8px 0 20px 0; 
                border: 1px solid #ccc; border-radius: 4px;
                box-sizing: border-box; transition: all 0.3s ease;
            }
            input:hover, button:hover {
                border-color: #007bff;
                background-color: #f0f8ff;
            }
            input:focus {
                border-color: #007bff;
                outline: none;
                box-shadow: 0 0 5px rgba(0,123,255,0.5);
            }
            button { 
                background-color: #4CAF50; color: white; padding: 12px 15px; 
                border: none; border-radius: 4px; cursor: pointer; width: 100%;
                font-size: 16px; font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="form-container">
            <h2>Test Form Agent (PyAutoGUI)</h2>
            <form id="tempForm">
                <label for="fullName">Full Name</label>
                <input type="text" id="fullName" name="fullName" placeholder="Enter your full name">
                
                <label for="email">Email Address</label>
                <input type="email" id="email" name="email" placeholder="Enter your email">
                
                <button type="button" id="submitBtn" onclick="alert('Form Submitted successfully!')">Submit Application</button>
            </form>
        </div>
    </body>
    </html>
    """
    
    html_path = os.path.abspath("temp_form.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    url = f"file:///{html_path.replace(chr(92), '/')}"
    print(f"Navigating to local form: {url}")
    page.goto(url)
    
    # Wait for the page to fully render and stabilize
    page.wait_for_timeout(2000)

    print("\n[WARNING] PyAutoGUI will now take control of your physical OS mouse cursor!")
    print("Please do not move your mouse for the next 10 seconds.")
    print("If you need to emergency stop, drag your mouse forcefully to any corner of your monitor.")
    time.sleep(2)

    # 1. Fill the "Full Name" input
    print("\n--- Processing Full Name ---")
    coords = get_element_screen_coordinates(page, "#fullName")
    if coords:
        print(f"Mapped DOM element to Monitor Coordinates: {coords}")
        human_mouse_move_pyautogui(coords[0], coords[1])
        time.sleep(0.2)
        pyautogui.click()
        time.sleep(0.3)
        human_type_pyautogui("John Doe")
    
    time.sleep(1)

    # 2. Fill the "Email" input
    print("\n--- Processing Email ---")
    coords = get_element_screen_coordinates(page, "#email")
    if coords:
        print(f"Mapped DOM element to Monitor Coordinates: {coords}")
        human_mouse_move_pyautogui(coords[0], coords[1])
        time.sleep(0.2)
        pyautogui.click()
        time.sleep(0.3)
        human_type_pyautogui("john.doe@example.com")
    
    time.sleep(1)

    # 3. Click Submit Button
    print("\n--- Processing Submit ---")
    coords = get_element_screen_coordinates(page, "#submitBtn")
    if coords:
        print(f"Mapped DOM element to Monitor Coordinates: {coords}")
        human_mouse_move_pyautogui(coords[0], coords[1])
        time.sleep(0.2)
        pyautogui.click()
    
    print("\nWaiting to display the success result...")
    time.sleep(4)
    
    # Clean up
    print("Closing browser session and cleaning up temp files...")
    manager.close()
    if os.path.exists(html_path):
        os.remove(html_path)

if __name__ == "__main__":
    main()
