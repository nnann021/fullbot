import os
import shutil
import sys
import time
import re
import json
import getpass
import random
import subprocess
from PIL import Image
from pyzbar.pyzbar import decode
import qrcode_terminal
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException, ElementClickInterceptedException
from datetime import datetime, timedelta

def load_settings():
    global settings, settings_file
    # Default settings with all necessary keys
    default_settings = {
        "forceClaim": False,
        "debugIsOn": False,
        "hideSensitiveInput": True,
        "screenshotQRCode": True,
        "maxSessions": 1,
        "verboseLevel": 2,
        "lowestClaimOffset": 0, # One/both be a negative figure to claim before reaches filled status.
        "highestClaimOffset": 15, # Or one/both can be positive to claim after the pot is filled.
        "forceNewSession": False,
    }

    if os.path.exists(settings_file):
        with open(settings_file, "r") as f:
            loaded_settings = json.load(f)
        # Update default settings with any settings loaded from the file
        settings = {**default_settings, **loaded_settings}
        output("Settings loaded successfully.", 3)
    else:
        settings = default_settings
        save_settings()  # Save the default settings if the file does not exist

def save_settings():
    global settings, settings_file
    with open(settings_file, "w") as f:
        json.dump(settings, f)
    output("Settings saved successfully.", 3)

def output(string, level):
    if settings['verboseLevel'] >= level:
        print(string)

# Define sessions and settings files
settings_file = "variables.txt"
status_file_path = "status.txt"
settings = {}
load_settings()
driver = None
target_element = None
random_offset = random.randint(settings['lowestClaimOffset'], settings['highestClaimOffset'])

def increase_step():
    global step
    step_int = int(step) + 1
    step = f"{step_int:02}"

print("Initialising the HOT Wallet Auto-claim Python Script - Good Luck!")

def update_settings():
    global settings
    load_settings()  # Assuming this function is defined to load settings from a file or similar source

    output("\nCurrent settings:",1)
    for key, value in settings.items():
        output(f"{key}: {value}",1)

    # Function to simplify the process of updating settings
    def update_setting(setting_key, message, default_value):
        current_value = settings.get(setting_key, default_value)
        response = input(f"\n{message} (Y/N, press Enter to keep current [{current_value}]): ").strip().lower()
        if response == "y":
            settings[setting_key] = True
        elif response == "n":
            settings[setting_key] = False

    update_setting("forceClaim", "Shall we force a claim on first run? Does not wait for the timer to be filled", settings["forceClaim"])
    update_setting("debugIsOn", "Should we enable debugging? This will save screenshots in your local drive", settings["debugIsOn"])
    update_setting("hideSensitiveInput", "Should we hide sensitive input? Your phone number and seed phrase will not be visible on the screen", settings["hideSensitiveInput"])
    update_setting("screenshotQRCode", "Shall we allow log in by QR code? The alternative is by phone number and one-time password", settings["screenshotQRCode"])
        
    try:
        new_max_sessions = int(input(f"\nEnter the number of max concurrent claim sessions. Additional claims will queue until a session slot is free.\n(current: {settings['maxSessions']}): "))
        settings["maxSessions"] = new_max_sessions
    except ValueError:
        output("Number of sessions remains unchanged.",1)

    try:
        new_verbose_level = int(input("\nEnter the number for how much information you want displaying in the console.\n 3 = all messages, 2 = claim steps, 1 = minimal steps\n(current: {}): ".format(settings['verboseLevel'])))
        if 1 <= new_verbose_level <= 3:
            settings["verboseLevel"] = new_verbose_level
            output("Verbose level updated successfully.", 2)
        else:
            output("Verbose level remains unchanged.", 2)
    except ValueError:
        output("Invalid input. Verbose level remains unchanged.", 2)

    try:
        new_lowest_offset = int(input("\nEnter the lowest possible offset for the claim timer (valid values are -30 to +30 minutes)\n(current: {}): ".format(settings['lowestClaimOffset'])))
        if -30 <= new_lowest_offset <= 30:
            settings["lowestClaimOffset"] = new_lowest_offset
            output("Lowest claim offset updated successfully.", 2)
        else:
            output("Invalid range for lowest claim offset. Please enter a value between -30 and +30.", 2)
    except ValueError:
        output("Invalid input. Lowest claim offset remains unchanged.", 2)

    try:
        new_highest_offset = int(input("\nEnter the highest possible offset for the claim timer (valid values are 0 to 60 minutes)\n(current: {}): ".format(settings['highestClaimOffset'])))
        if 0 <= new_highest_offset <= 60:
            settings["highestClaimOffset"] = new_highest_offset
            output("Highest claim offset updated successfully.", 2)
        else:
            output("Invalid range for highest claim offset. Please enter a value between 0 and 60.", 2)
    except ValueError:
        output("Invalid input. Highest claim offset remains unchanged.", 2)

    # Ensure lowestClaimOffset is not greater than highestClaimOffset
    if settings["lowestClaimOffset"] > settings["highestClaimOffset"]:
        settings["lowestClaimOffset"] = settings["highestClaimOffset"]
        output("Adjusted lowest claim offset to match the highest as it was greater.", 2)

    save_settings()

    update_setting("forceNewSession", "Overwrite existing session and Force New Login? Use this if your saved session has crashed\nOne-Time only (setting not saved): ", settings["forceNewSession"])

    output("\nRevised settings:",1)
    for key, value in settings.items():
        output(f"{key}: {value}",1)
    output("",1)

# Set up paths and sessions:
user_input = ""
session_path = "./selenium/{}".format(user_input)
os.makedirs(session_path, exist_ok=True)
screenshots_path = "./screenshots/{}".format(user_input)
os.makedirs(screenshots_path, exist_ok=True)
output(f"Our screenshot path is {screenshots_path}",3)
backup_path = "./backups/{}".format(user_input)
os.makedirs(backup_path, exist_ok=True)
output(f"Our screenshot path is {backup_path}",3)

def get_session_id():
    global settings
    """Prompts the user for a session ID or determines the next sequential ID based on a 'Wallet' prefix.

    Returns:
        str: The entered session ID or the automatically generated sequential ID.
    """

    user_input = input("Enter your unique Session Name here, or hit <enter> for the next sequential wallet: ")
    user_input = user_input.strip()

    # Check for existing session folders
    screenshots_dir = "./screenshots/"
    dir_contents = os.listdir(screenshots_dir)
    # Filter directories with the 'Wallet' prefix and extract the numeric parts
    wallet_dirs = [int(dir_name.replace('Wallet', '')) for dir_name in dir_contents if dir_name.startswith('Wallet') and dir_name[6:].isdigit()]
    next_wallet_id = 1
    if wallet_dirs:
        highest_wallet_id = max(wallet_dirs)
        next_wallet_id = highest_wallet_id + 1

    # Use the next sequential wallet ID if no user input was provided
    if not user_input:
        user_input = f"Wallet{next_wallet_id}"
    return user_input

# Update the settings based on user input
if len(sys.argv) > 1:
        user_input = sys.argv[1]  # Get session ID from command-line argument
        output(f"Session ID provided: {user_input}",2)
        # Safely check for a second argument
        if len(sys.argv) > 2 and sys.argv[2] == "debug":
            settings['debugIsOn'] = True
else:
    user_input = input("Should we update our settings? (Default:<enter> / Yes = y): ").strip().lower()
    if user_input == "y":
        update_settings()
    user_input = get_session_id()


session_path = "./selenium/{}".format(user_input)
os.makedirs(session_path, exist_ok=True)
screenshots_path = "./screenshots/{}".format(user_input)
os.makedirs(screenshots_path, exist_ok=True)
backup_path = "./backups/{}".format(user_input)
os.makedirs(backup_path, exist_ok=True)

# Define our base path for debugging screenshots
screenshot_base = os.path.join(screenshots_path, "screenshot")

def setup_driver(chromedriver_path):

    service = Service(chromedriver_path)
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("user-data-dir={}".format(session_path))
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--log-level=3")  # Set log level to suppress INFO and WARNING messages
    chrome_options.add_argument("--disable-bluetooth")
    chrome_options.add_argument("--mute-audio")
    # chrome_options.add_argument("--incognito")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    chrome_options.add_experimental_option("detach", True)

    # Compatibility Handling and error testing:
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        output(f"Initial ChromeDriver setup may have failed: {e}",1)
        output("Please ensure you have the correct ChromeDriver version for your system.",1)
        output("If you copied the GitHub commands, ensure all lines executed.",1)
        output("Visit https://chromedriver.chromium.org/downloads to find the right version.",1)
        exit(1)

# Enter the correct the path to your ChromeDriver here
chromedriver_path = "/usr/local/bin/chromedriver"

def get_driver():
    global driver
    if driver is None:  # Check if driver needs to be initialized
        driver = setup_driver(chromedriver_path)
        load_cookies()
    return driver

def load_cookies():
    global driver
    cookies_path = f"{session_path}/cookies.json"
    if os.path.exists(cookies_path):
        with open(cookies_path, 'r') as file:
            cookies = json.load(file)
            for cookie in cookies:
                driver.add_cookie(cookie)

def quit_driver():
    global driver
    if driver:
        driver.quit()
        driver = None
        
def manage_session():
    current_session = session_path
    current_timestamp = int(time.time())

    while True:
        try:
            with open(status_file_path, "r+") as file:
                status = json.load(file)

                # Clean up expired sessions
                for session_id, timestamp in list(status.items()):  # Important to iterate over a copy
                    if current_timestamp - timestamp > 300:  # 5 minutes
                        del status[session_id]
                        output(f"Removed expired session: {session_id}",3)

                # Check for available slots
                if len(status) < settings['maxSessions']:
                    status[current_session] = current_timestamp
                    file.seek(0)  # Rewind to beginning
                    json.dump(status, file)
                    file.truncate()  # Ensure clean overwrite
                    output(f"Session started: {current_session} in {status_file_path}",3)
                    break  # Exit the loop once session is acquired

            output(f"Waiting for slot. Current sessions: {len(status)}/{settings['maxSessions']}",3)
            time.sleep(random.randint(20, 40))

        except FileNotFoundError:
            # Create file if it doesn't exist
            with open(status_file_path, "w") as file:
                json.dump({}, file)
        except json.decoder.JSONDecodeError:
            # Handle empty or corrupt JSON 
            output("Corrupted status file. Resetting...",3)
            with open(status_file_path, "w") as file:
                json.dump({}, file)
 
def log_into_telegram():
    global driver, target_element, session_path, screenshots_path, backup_path, settings, step
    step = "01"

    def visible_QR_code():
        global driver, screenshots_path, step
        max_attempts = 5
        attempt_count = 0
        last_url = "not a url"  # Placeholder for the last detected QR code URL

        xpath = "//canvas[@class='qr-canvas']"
        driver.get("https://web.telegram.org/k/#@herewalletbot")

        while attempt_count < max_attempts:
            try:

                wait = WebDriverWait(driver, 5)
                QR_code = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
                QR_code.screenshot(f"{screenshots_path}/Step {step} - Initial QR code.png")
                image = Image.open(f"{screenshots_path}/Step {step} - Initial QR code.png")
                decoded_objects = decode(image)
                if decoded_objects:
                    this_url = decoded_objects[0].data.decode('utf-8')
                    if this_url != last_url:
                        last_url = this_url  # Update the last seen URL
                        clear_screen()
                        attempt_count += 1
                        output("*** Important: Having @HereWalletBot open in your Telegram App might stop this script from logging in! ***\n", 2)
                        output(f"Step {step} - Our screenshot path is {screenshots_path}\n", 1)
                        output(f"Step {step} - Generating screenshot {attempt_count} of {max_attempts}\n", 2)
                        qrcode_terminal.draw(this_url)
                    if attempt_count >= max_attempts:
                        output(f"Step {step} - Max attempts reached with no new QR code.", 1)
                        return False
                    time.sleep(2)  # Wait before the next check
                else:
                    time.sleep(2)  # No QR code decoded, wait before retrying
            except TimeoutException:
                output(f"Step {step} - QR Code is no longer visible.", 2)
                return True  # Indicates the QR code has been scanned or disappeared
        
        output(f"Step {step} - Failed to generate a valid QR code after multiple attempts.", 1)
        return False  # If loop completes without a successful scan

    if os.path.exists(session_path):
        shutil.rmtree(session_path)
    os.makedirs(session_path, exist_ok=True)
    if os.path.exists(screenshots_path):
        shutil.rmtree(screenshots_path)
    os.makedirs(screenshots_path, exist_ok=True)
    if os.path.exists(backup_path):
        shutil.rmtree(backup_path)
    os.makedirs(backup_path, exist_ok=True)

    driver = get_driver()
    
    # QR Code Method
    if settings['screenshotQRCode']:
        try:

            while True:
                if visible_QR_code():  # QR code not found
                    test_for_2fa()
                    return  # Exit the function entirely

                # If we reach here, it means the QR code is still present:
                choice = input(f"\nStep {step} - QR Code still present. Retry (r) with a new QR code or switch to the OTP method (enter): ")
                print("")
                if choice.lower() == 'r':
                    visible_QR_code()
                else:
                    break

        except TimeoutException:
            output(f"Step {step} - Canvas not found: Restart the script and retry the QR Code or switch to the OTP method.", 1)

    # OTP Login Method
    increase_step()
    output(f"Step {step} - Initiating the One-Time Password (OTP) method...\n",1)
    driver.get("https://web.telegram.org/k/#@herewalletbot")
    xpath = "//button[contains(@class, 'btn-primary') and contains(., 'Log in by phone Number')]"
    move_and_click(xpath, 30, True, "switch to log in by phone number", step, "clickable")
    increase_step()

    # Country Code Selection
    xpath = "//div[@class='input-field-input']//span[@class='i18n']"    
    target_element = move_and_click(xpath, 30, True, "update users country", step, "clickable")
    user_input = input(f"Step {step} - Please enter your Country Name as it appears in the Telegram list: ").strip()  
    target_element.send_keys(user_input)
    target_element.send_keys(Keys.RETURN)
    increase_step()

    # Phone Number Input
    xpath = "//div[@class='input-field-input' and @inputmode='decimal']"
    target_element = move_and_click(xpath, 30, True, "request users phone number", step, "clickable")
    def validate_phone_number(phone):
        # Regex for validating an international phone number without leading 0 and typically 7 to 15 digits long
        pattern = re.compile(r"^[1-9][0-9]{6,14}$")
        return pattern.match(phone)

    while True:
        if settings['hideSensitiveInput']:
            user_phone = getpass.getpass(f"Step {step} - Please enter your phone number without leading 0 (hidden input): ")
        else:
            user_phone = input(f"Step {step} - Please enter your phone number without leading 0 (visible input): ")
    
        if validate_phone_number(user_phone):
            output(f"Step {step} - Valid phone number entered.",3)
            break
        else:
            output(f"Step {step} - Invalid phone number, must be 7 to 15 digits long and without leading 0.",1)
    target_element.send_keys(user_phone)
    increase_step()

    # Wait for the "Next" button to be clickable and click it    
    xpath = "//button[contains(@class, 'btn-primary') and .//span[contains(text(), 'Next')]]"
    move_and_click(xpath, 5, True, "click next to proceed to OTP entry", step, "visible")
    increase_step()

    try:
        # Attempt to locate and interact with the OTP field
        wait = WebDriverWait(driver, 20)
        password = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='tel']")))
        if settings['debugIsOn']:
            time.sleep(3)
            driver.save_screenshot(f"{screenshots_path}/Step {step} - Ready_for_OTP.png")
        otp = input(f"Step {step} - What is the Telegram OTP from your app? ")
        password.click()
        password.send_keys(otp)
        output(f"Step {step} - Let's try to log in using your Telegram OTP.\n",3)

    except TimeoutException:
        # OTP field not found 
        output(f"Step {step} - OTP entry has failed - maybe you entered the wrong code, or possible flood cooldown issue.",1)

    except Exception as e:  # Catch any other unexpected errors
        output(f"Step {step} - Login failed. Error: {e}", 1) 
        if settings['debugIsOn']:
            driver.save_screenshot(f"{screenshots_path}/Step {step} - error_Something_Occured.png")

    increase_step()
    test_for_2fa()

    if settings['debugIsOn']:
        time.sleep(3)
        driver.save_screenshot(f"{screenshots_path}/Step {step} - After_Entering_OTP.png")

def test_for_2fa():
    global settings, driver, screenshots_path, step
    try:
        increase_step()
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        xpath = "//input[@type='password' and contains(@class, 'input-field-input')]"
        fa_input = move_and_click(xpath, 5, False, "check for 2FA requirement (will timeout if you don't have 2FA)", step, "present")
        if fa_input:
            if settings['hideSensitiveInput']:
                tg_password = getpass.getpass(f"Step {step} - Enter your Telegram 2FA password: ")
            else:
                tg_password = input(f"Step {step} - Enter your Telegram 2FA password: ")
            fa_input.send_keys(tg_password + Keys.RETURN)
            output(f"Step {step} - 2FA password sent.\n", 3)
            output(f"Step {step} - Checking if the 2FA password is correct.\n", 2)
            xpath = "//*[contains(text(), 'Incorrect password')]"
            try:
                incorrect_password = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.XPATH, xpath)))
                output(f"Step {step} - 2FA password is marked as incorrect by Telegram - check your debug screenshot if active.", 1)
                if settings['debugIsOn']:
                    screenshot_path = f"{screenshots_path}/Step {step} - Test QR code after session is resumed.png"
                    driver.save_screenshot(screenshot_path)
                sys.exit()  # Exit if incorrect password is detected
            except TimeoutException:
                pass

            output(f"Step {step} - No password error found.", 3)
            xpath = "//input[@type='password' and contains(@class, 'input-field-input')]"
            fa_input = move_and_click(xpath, 5, False, "final check to make sure we are correctly logged in", step, "present")
            if fa_input:
                output(f"Step {step} - 2FA password entry is still showing, check your debug screenshots for further information.\n", 1)
                sys.exit()
            output(f"Step {step} - 2FA password check appears to have passed OK.\n", 3)
        else:
            output(f"Step {step} - 2FA input field not found.\n", 1)

    except TimeoutException:
        # 2FA field not found
        output(f"Step {step} - Two-factor Authorization not required.\n", 3)

    except Exception as e:  # Catch any other unexpected errors
        output(f"Step {step} - Login failed. 2FA Error - you'll probably need to restart the script: {e}", 1)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/Step {step} - error: Something Bad Occured.png"
            driver.save_screenshot(screenshot_path)

def next_steps():
    global driver, target_element, settings, backup_path, session_path, step
    driver = get_driver()
    increase_step()
    try:
        driver.get("https://tgapp.herewallet.app/auth/import")
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        
        # Then look for the seed phase textarea:
        xpath = "//p[contains(text(), 'Seed or private key')]/ancestor-or-self::*/textarea"
        input_field = move_and_click(xpath, 30, True, "locate seedphrase textbox", step, "clickable")
        input_field.send_keys(validate_seed_phrase()) 
        output(f"Step {step} - Was successfully able to enter the seed phrase...",3)
        increase_step()

        # Click the continue button after seed phrase entry:
        xpath = "//button[contains(text(), 'Continue')]"
        move_and_click(xpath, 30, True, "click continue after seedphrase entry", step, "clickable")
        increase_step()

        # Click the account selection button:
        xpath = "//button[contains(text(), 'Select account')]"
        move_and_click(xpath, 120, True, "click continue at account selection screen", step, "clickable")
        increase_step()

        # Click on the Storage link:
        xpath = "//h4[text()='Storage']"
        move_and_click(xpath, 30, True, "click the 'storage' link", step, "clickable")
        cookies_path = f"{session_path}/cookies.json"
        cookies = driver.get_cookies()
        with open(cookies_path, 'w') as file:
            json.dump(cookies, file)

    except TimeoutException:
        output(f"Step {step} - Failed to find or switch to the iframe within the timeout period.",1)

    except Exception as e:
        output(f"Step {step} - An error occurred: {e}",1)

def full_claim():
    global driver, target_element, settings, session_path, step, random_offset
    step = "100"
    driver = get_driver()
    output("\nCHROME DRIVER INITIALISED: If the script exits before detaching, the session may need to be restored.",1)

    def apply_random_offset(unmodifiedTimer):
        global settings, step, random_offset
        if settings['lowestClaimOffset'] <= settings['highestClaimOffset']:
            random_offset = random.randint(settings['lowestClaimOffset'], settings['highestClaimOffset'])
            modifiedTimer = unmodifiedTimer + random_offset
            output(f"Step {step} - Random offset applied to the wait timer of: {random_offset} minutes.", 2)
            return modifiedTimer

    try:
        driver.get("https://web.telegram.org/k/#@herewalletbot")
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        output(f"Step {step} - Attempting to verify if we are logged in (hopefully QR code is not present).",3)
        xpath = "//canvas[@class='qr-canvas']"
        wait = WebDriverWait(driver, 5)
        wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/Step {step} - Test QR code after session is resumed.png"
            driver.save_screenshot(screenshot_path)
        output(f"Step {step} - Chrome driver reports the QR code is visible: It appears we are no longer logged in.",1)
        output(f"Step {step} - Most likely you will get a warning that the central input box is not found.",2)
        output(f"Step {step} - System will try to restore session, or restart the script from CLI force a fresh log in.\n",1)

    except TimeoutException:
        output(f"Step {step} - nothing found to action. The QR code test passed.\n",3)
    increase_step()

    driver.get("https://web.telegram.org/k/#@herewalletbot")
    WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')

    if settings['debugIsOn']:
        time.sleep(3)
        driver.save_screenshot(f"{screenshots_path}/Step {step} Pre-Claim screenshot.png")

    # There is a very unlikely scenario that the chat might have been cleared.
    # In this case, the "START" button needs pressing to expose the chat window!
    xpath = "//button[contains(., 'START')]"
    move_and_click(xpath, 5, True, "check for the start button (should not be present)", step, "clickable")
    increase_step()

    # Let's try to send the start command:
    send_start(step)
    increase_step()

    # Now let's try to find a working link to open the launch button
    find_working_link(step)
    increase_step()

    # Now let's move to and JS click the "Launch" Button
    xpath = "//button[contains(@class, 'popup-button') and contains(., 'Launch')]"
    move_and_click(xpath, 30, True, "click the 'Launch' button", step, "clickable")
    increase_step()

    # HereWalletBot Pop-up Handling
    select_iframe(step)
    increase_step()

    # Click on the Storage link:
    xpath = "//h4[text()='Storage']"
    move_and_click(xpath, 30, True, "click the 'storage' link", step, "clickable")
    increase_step

    try:
        element = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//p[contains(text(), 'HOT Balance:')]/following-sibling::p[1]")
            )
        )
    
        # Retrieve the entire block of text within the parent div of the found <p> element
        if element is not None:
            parent_div = element.find_element(By.XPATH, "./..")
            text_content = parent_div.text 
            balance_part = text_content.split("HOT Balance:\n")[1].strip() if "HOT Balance:\n" in text_content else "No balance info"
            output(f"Step {step} - HOT balance prior to claim: {balance_part}", 3)

    except NoSuchElementException:
        output(f"Step {step} - Element containing 'HOT Balance:' was not found.", 3)
    except Exception as e:
        print(f"Step {step} - An error occurred:", e)
    increase_step()

    wait_time_text = get_wait_time(step, "pre-claim") 

    if wait_time_text != "Filled":
        matches = re.findall(r'(\d+)([hm])', wait_time_text)
        remaining_wait_time = (sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches)) + random_offset
        if remaining_wait_time < 5:
            settings['forceClaim'] = True
            output(f"Step {step} - the remaining time to claim is less than the random offset, so applying: settings['forceClaim'] = True", 3)
        else:
            output(f"Step {step} - the remaining time is {remaining_wait_time} minutes, so going back to wait.", 2)
            return remaining_wait_time

    if wait_time_text == "Unknown":
      return 15

    try:
        output(f"Step {step} - The pre-claim wait time is : {wait_time_text} and random offset is {random_offset} minutes.",1)
        increase_step()

        if wait_time_text == "Filled" or settings['forceClaim']:
            try:
                original_window = driver.current_window_handle
                xpath = "//button[contains(text(), 'Check NEWS')]"
                move_and_click(xpath, 10, True, "check for NEWS.", step, "clickable")
                driver.switch_to.window(original_window)
            except TimeoutException:
                if settings['debugIsOn']:
                    output(f"Step {step} - No news to check or button not found.",3)
            increase_step()

            try:
                # Let's double check if we have to reselect the iFrame after news
                # HereWalletBot Pop-up Handling
                select_iframe(step)
                increase_step()
                
                # Click on the "Claim HOT" button:
                xpath = "//button[contains(text(), 'Claim HOT')]"
                move_and_click(xpath, 30, True, "click the claim button", step, "clickable")
                increase_step()

                # Now let's try again to get the time remaining until filled. 
                # 4th April 24 - Let's wait for the spinner to disappear before trying to get the new time to fill.
                output(f"Step {step} - Let's wait for the pending Claim spinner to stop spinning...",2)
                time.sleep(5)
                wait = WebDriverWait(driver, 240)
                spinner_xpath = "//*[contains(@class, 'spinner')]" 
                try:
                    wait.until(EC.invisibility_of_element_located((By.XPATH, spinner_xpath)))
                    output(f"Step {step} - Pending action spinner has stopped.\n",3)
                except TimeoutException:
                    output(f"Step {step} - Looks like the site has lag - the Spinner did not disappear in time.\n",2)
                increase_step()
                wait_time_text = get_wait_time(step, "post-claim") 
                matches = re.findall(r'(\d+)([hm])', wait_time_text)
                total_wait_time = apply_random_offset(sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches))
                increase_step()

                try:
                  element = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.XPATH, "//p[contains(text(), 'HOT Balance:')]/following-sibling::p[1]")))
                  if element is not None:
                    parent_div = element.find_element(By.XPATH, "./..")
                    text_content = parent_div.text 
                    balance_part = text_content.split("HOT Balance:\n")[1].strip() if "HOT Balance:\n" in text_content else "No balance info"
                    output(f"Step {step} - HOT balance after claim: {balance_part}", 1)
                except NoSuchElementException:
                    output(f"Step {step} - Element containing 'HOT Balance:' was not found.", 3)
                except Exception as e:
                    print(f"Step {step} - An error occurred:", e)

                if wait_time_text == "Filled":
                    output(f"Step {step} - The wait timer is still showing: Filled.",1)
                    output(f"Step {step} - This means either the claim failed, or there is >4 minutes lag in the game.",1)
                    output(f"Step {step} - We'll check back in 1 hour to see if the claim processed and if not try again.",2)
                else:
                    output(f"Step {step} - Post claim raw wait time: %s & proposed new wait timer = %s minutes." % (wait_time_text, total_wait_time),1)
                return max(60, total_wait_time)

            except TimeoutException:
                output(f"Step {step} - The claim process timed out: Maybe the site has lag? Will retry after one hour.",2)
                return 60
            except Exception as e:
                output(f"Step {step} - An error occurred while trying to claim: {e}\nLet's wait an hour and try again",1)
                return 60

        else:
            # If the wallet isn't ready to be claimed, calculate wait time based on the timer provided on the page
            matches = re.findall(r'(\d+)([hm])', wait_time_text)
            if matches:
                total_time = sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches)
                total_time += 1
                total_time = max(5, total_time) # Wait at least 5 minutes or the time
                output(f"Step {step} - Not Time to claim this wallet yet. Wait for {total_time} minutes until the storage is filled.",2)
                return total_time 
            else:
                output(f"Step {step} - No wait time data found? Let's check again in one hour.",2)
                return 60  # Default wait time when no specific time until filled is found.
    except Exception as e:
        output(f"Step {step} - An unexpected error occurred: {e}",1)
        return 60  # Default wait time in case of an unexpected error
        
def get_wait_time(step_number="108", beforeAfter = "pre-claim", max_attempts=2):
    
    for attempt in range(1, max_attempts + 1):
        try:
            xpath = "//div[contains(., 'Storage')]//p[contains(., 'Filled') or contains(., 'to fill')]"
            wait_time_element = move_and_click(xpath, 20, True, f"get the {beforeAfter} wait timer", step, "visible")
            # Check if wait_time_element is not None
            if wait_time_element is not None:
                return wait_time_element.text
            else:
                output(f"Step {step} - Attempt {attempt}: Wait time element not found. Clicking the 'Storage' link and retrying...",3)
                storage_xpath = "//h4[text()='Storage']"
                move_and_click(storage_xpath, 30, True, "click the 'storage' link", f"{step} recheck", "clickable")
                output(f"Step {step} - Attempted to select strorage again...",3)
            return wait_time_element.text

        except TimeoutException:
            if attempt < max_attempts:  # Attempt failed, but retries remain
                output(f"Step {step} - Attempt {attempt}: Wait time element not found. Clicking the 'Storage' link and retrying...",3)
                storage_xpath = "//h4[text()='Storage']"
                move_and_click(storage_xpath, 30, True, "click the 'storage' link", f"{step} recheck", "clickable")
            else:  # No retries left after initial failure
                output(f"Step {step} - Attempt {attempt}: Wait time element not found.",3)

        except Exception as e:
            output(f"Step {step} - An error occurred on attempt {attempt}: {e}",3)

    # If all attempts fail         
    return "Unknown"

def clear_screen():
    # Attempt to clear the screen after entering the seed phrase or mobile phone number.
    # For Windows
    if os.name == 'nt':
        os.system('cls')
    # For macOS and Linux
    else:
        os.system('clear')

def select_iframe(old_step):
    global driver, screenshots_path, settings, step
    output(f"Step {step} - Attempting to switch to the app's iFrame...",2)

    try:
        wait = WebDriverWait(driver, 20)
        popup_body = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "popup-body")))
        iframe = popup_body.find_element(By.TAG_NAME, "iframe")
        driver.switch_to.frame(iframe)
        output(f"Step {step} - Was successfully able to switch to the app's iFrame.\n",3)

        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-iframe-switched.png"
            driver.save_screenshot(screenshot_path)

    except TimeoutException:
        output(f"Step {step} - Failed to find or switch to the iframe wit,h,in, the timeout period.\n",3)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-iframe-timeout.png"
            driver.save_scre,enshot(screenshot_path)
    except Exception as e:
        output(f"Step {step} - An error occurred while attempting to switch to the iframe: {e}\n",3)
        if settings['debugIsOn']:
            screenshot_pat,h = f"{screenshots_path}/{step}-iframe-error.png"
            driver.save_screenshot(screenshot_path)

def find_working_link(old_step):
    global driver, screenshots_path, settings, step
    output(f"Step {step} - Attempting to open a link for the app...",2)

    start_app_xpath = "//a[@href='https://t.me/herewalletbot/app']"
    try:
        start_app_buttons = WebDriverWait(driver, 30).until(EC.presence_of_all_elements_located((By.XPATH, start_app_xpath)))
        clicked = False

        for button in reversed(start_app_buttons):
            actions = ActionChains(driver)
            actions.move_to_element(button).pause(0.2)
            try:
                if settings['debugIsOn']:
                    driver.save_screenshot(f"{screenshots_path}/{step} - Find working link.png".format(screenshots_path))
                actions.perform()
                driver.execute_script("arguments[0].click();", button)
                clicked = True
                break
            except StaleElementReferenceException:
                continue
            except ElementClickInterceptedException:
                continue

        if not clicked:
            output(f"Step {step} - None of the 'Open Wallet' buttons were clickable.\n",1)
            if settings['debugIsOn']:
                screenshot_path = f"{screenshots_path}/{step}-no-clickable-button.png"
                driver.save_screenshot(screenshot_path)
        else:
            output(f"Step {step} - Successfully able to open a link for the app..\n",3)
            if settings['debugIsOn']:
                screenshot_path = f"{screenshots_path}/{step}-app-opened.png"
                driver.save_screenshot(screenshot_path)

    except TimeoutException:
        output(f"Step {step} - Failed to find the 'Open Wallet' button within the expected timeframe.\n",1)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-timeout-finding-button.png"
            driver.save_screenshot(screenshot_path)
    except Exception as e:
        output(f"Step {step} - An error occurred while trying to open the app: {e}\n",1)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-unexpected-error-opening-app.png"
            driver.save_screenshot(screenshot_path)


def send_start(old_step):
    global driver, screenshots_path, backup_path, settings, step
    xpath = "//div[contains(@class, 'input-message-container')]/div[contains(@class, 'input-message-input')][1]"
    
    def attempt_send_start():
        chat_input = move_and_click(xpath, 30, False, "find the chat window/message input box", step, "present")
        if chat_input:
            increase_step()
            output(f"Step {step} - Attempting to send the '/start' command...",2)
            chat_input.send_keys("/start")
            chat_input.send_keys(Keys.RETURN)
            output(f"Step {step} - Successfully sent the '/start' command.\n",3)
            if settings['debugIsOn']:
                screenshot_path = f"{screenshots_path}/{step}-sent-start.png"
                driver.save_screenshot(screenshot_path)
            return True
        else:
            output(f"Step {step} - Failed to find the message input box.\n",1)
            return False

    if not attempt_send_start():
        # Attempt failed, try restoring from backup and retry
        output(f"Step {step} - Attempting to restore from backup and retry.\n",2)
        if restore_from_backup():
            if not attempt_send_start():  # Retry after restoring backup
                output(f"Step {step} - Retried after restoring backup, but still failed to send the '/start' command.\n",1)
        else:
            output(f"Step {step} - Backup restoration failed or backup directory does not exist.\n",1)

def restore_from_backup():
    if os.path.exists(backup_path):
        try:
            quit_driver()
            shutil.rmtree(session_path)
            shutil.copytree(backup_path, session_path, dirs_exist_ok=True)
            driver = get_driver()
            driver.get("https://web.telegram.org/k/#@herewalletbot")
            WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
            output(f"Step {step} - Backup restored successfully.\n",2)
            return True
        except Exception as e:
            output(f"Step {step} - Error restoring backup: {e}\n",1)
            return False
    else:
        output(f"Step {step} - Backup directory does not exist.\n",1)
        return False

def move_and_click(xpath, wait_time, click, action_description, old_step, expectedCondition):
    global driver, screenshots_path, settings, step
    target_element = None
    failed = False

    output(f"Step {step} - Attempting to {action_description}...", 2)

    try:
        wait = WebDriverWait(driver, wait_time)
        # Check and prepare the element based on the expected condition
        if expectedCondition == "visible":
            target_element = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
        elif expectedCondition == "present":
            target_element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        elif expectedCondition == "invisible":
            wait.until(EC.invisibility_of_element_located((By.XPATH, xpath)))
            return None  # Early return as there's no element to interact with
        elif expectedCondition == "clickable":
            target_element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))

        # Before interacting, check for and remove overlays if click is needed or visibility is essential
        if click or expectedCondition in ["visible", "clickable"]:
            clear_overlays(target_element, step)

        # Perform actions if the element is found and clicking is requested
        if click and target_element:
            try:
                actions = ActionChains(driver)
                actions.move_to_element(target_element).pause(0.2).click().perform()
                output(f"Step {step} - Successfully able to {action_description} using ActionChains.", 3)
            except ElementClickInterceptedException:
                output("Step {step} - Element click intercepted, attempting JavaScript click as fallback...", 3)
                driver.execute_script("arguments[0].click();", target_element)
                output(f"Step {step} - Was able to {action_description} using JavaScript fallback.", 3)

    except TimeoutException:
        output(f"Step {step} - Timeout while trying to {action_description}.", 3)
    except Exception as e:
        output(f"Step {step} - An error occurred while trying to {action_description}: {e}", 1)
    finally:
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-{action_description}.png"
            driver.save_screenshot(screenshot_path)
        return target_element

def clear_overlays(target_element, old_step):
    # Get the location of the target element
    element_location = target_element.location_once_scrolled_into_view
    overlays = driver.find_elements(By.XPATH, "//*[contains(@style,'position: absolute') or contains(@style,'position: fixed')]")
    for overlay in overlays:
        overlay_rect = overlay.rect
        # Check if overlay covers the target element
        if (overlay_rect['x'] <= element_location['x'] <= overlay_rect['x'] + overlay_rect['width'] and
            overlay_rect['y'] <= element_location['y'] <= overlay_rect['y'] + overlay_rect['height']):
            driver.execute_script("arguments[0].style.display = 'none';", overlay)
            output(f"Step {step} - Removed an overlay covering the target.", 3)

def validate_seed_phrase():
    # Let's take the user inputed seed phrase and carry o,,ut basic validation
    while True:
        # Prompt the user for their seed phrase
        if settings['hideSensitiveInput']:
            seed_phrase = getpass.getpass(f"Step {step} - Please enter your 12-word seed phrase (your input is hidden): ")
        else:
            seed_phrase = input(f"Step {step} - Please enter your 12-word seed phrase (your input is visible): ")
        try:
            if not seed_phrase:
              raise ValueError(f"Step {step} - Seed phrase cannot be empty.")

            words = seed_phrase.split()
            if len(words) != 12:
                raise ValueError(f"Step {step} - Seed phrase must contain exactly 12 words.")

            pattern = r"^[a-z ]+$"
            if not all(re.match(pattern, word) for word in words):
                raise ValueError(f"Step {step} - Seed phrase can only contain lowercase letters and spaces.")
            return seed_phrase  # Return if valid

        except ValueError as e:
            output(f"Error: {e}",1)

# Start a new PM2 process
def start_pm2_app(script_path, app_name, session_name):
    command = f"pm2 start {script_path} --name {app_name} -- {session_name}"
    subprocess.run(command, shell=True, check=True)

# List all PM2 processes
def save_pm2():
    command = "pm2 save"
    result = subprocess.run(command, shell=True, text=True, capture_output=True)
    print(result.stdout)

def main():
    global session_path, settings, step
    driver = get_driver()
    quit_driver()
    clear_screen()
    if not settings["forceNewSession"]:
        load_settings()
    cookies_path = os.path.join(session_path, 'cookies.json')
    if os.path.exists(cookies_path) and not settings['forceNewSession']:
        output("Resuming the previous session...",2)
    else:
        output("Starting the Telegram & HereWalletBot login process...",2)
        log_into_telegram()
        quit_driver()
        next_steps()
        quit_driver()
        try:
            shutil.copytree(session_path, backup_path, dirs_exist_ok=True)
            output("We backed up the session data in case of a later crash!",3)
        except Exception as e:
            output("Oops, we weren't able to make a backup of the session data! Error:", 1)

        output("\nCHROME DRIVER DETACHED: It is safe to stop the script if you want to.\n",2)
        pm2_session = session_path.replace("./selenium/", "")
        output(f"You could add the new/updated session to PM use: pm2 start claim.py --name {pm2_session} -- {pm2_session}",1)
        user_choice = input("Enter 'y' to continue to 'claim' function, 'n' to exit or 'a' to add in PM2: ").lower()
        if user_choice == "n":
            output("Exiting script. You can resume the process later.",1)
            sys.exit()
        if user_choice == "a":
            start_pm2_app("claim.py", pm2_session, pm2_session)
            user_choice = input("Should we save your PM2 processes? (y, or enter to skip): ").lower()
            if user_choice == "y":
                save_pm2()
            output(f"You can now watch the session log into PM2 with: pm2 logs {pm2_session}",2)
            sys.exit()

    while True:
        manage_session()
        wait_time = full_claim()

        if os.path.exists(status_file_path):
            with open(status_file_path, "r+") as file:
                status = json.load(file)
                if session_path in status:
                    del status[session_path]
                    file.seek(0)
                    json.dump(status, file)
                    file.truncate()
                    output(f"Session released: {session_path}",3)

        quit_driver()
        output("\nCHROME DRIVER DETACHED: It is safe to stop the script if you want to.\n",1)
        
        now = datetime.now()
        next_claim_time = now + timedelta(minutes=wait_time)
        next_claim_time_str = next_claim_time.strftime("%H:%M")
        output(f"Need to wait until {next_claim_time_str} before the next claim attempt. Approximately {wait_time} minutes.",1)
        if settings["forceClaim"]:
            settings["forceClaim"] = False

        while wait_time > 0:
            this_wait = min(wait_time, 15)
            now = datetime.now()
            timestamp = now.strftime("%H:%M")
            output(f"[{timestamp}] Waiting for {this_wait} more minutes...",3)
            time.sleep(this_wait * 60)  # Convert minutes to seconds
            wait_time -= this_wait
            if wait_time > 0:
                output(f"Updated wait time: {wait_time} minutes left.",3)


if __name__ == "__main__":
    main()
