import subprocess
import time
import logging
import argparse
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("softue_monitor.log"),
        logging.StreamHandler()
    ]
)

def ping_host(host="192.168.100.1", count=1, timeout=3):
    """Try to ping the host and return True if successful, False otherwise."""
    try:
        # Using subprocess to run ping command with a timeout
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout * count + 2
        )
        return result.returncode == 0
    except subprocess.SubprocessError:
        return False

def run_softue(reflash=False):
    """Run the softUE with the specified parameters and return the process and whether reflash was used."""
    cmd = ["python", "ran.py", "-t", "ue", "--if_freq", "1"]
    
    if reflash:
        cmd.append("-f")
        logging.warning("Starting softUE with reflash option (-f)")
        wait_time = 60  # Wait 1 minute before checking pings after reflash
    else:
        logging.info("Starting softUE normally")
        wait_time = 15  # Wait 15 seconds before checking pings after normal start
    
    # Launch the process
    process = subprocess.Popen(cmd)
    
    return process, wait_time

def main():
    parser = argparse.ArgumentParser(description="softUE monitor with ping failover")
    parser.add_argument("--ping-interval", type=int, default=5, 
                        help="Interval in seconds between ping checks")
    parser.add_argument("--host", type=str, default="192.168.100.1",
                        help="Host to ping")
    parser.add_argument("--max-failures", type=int, default=15,
                        help="Number of consecutive ping failures before reflashing")
    parser.add_argument("--first-run-reflash", action="store_true", default=True,
                        help="Start with reflash (-f) on first run")
    args = parser.parse_args()
    
    logging.info("Starting softUE monitor script")
    
    consecutive_failures = 0
    
    # Start with reflash on first run if the flag is set
    softue_process, wait_time = run_softue(reflash=args.first_run_reflash)
    
    # Initial wait before starting ping checks
    logging.info(f"Waiting {wait_time} seconds before starting ping checks")
    time.sleep(wait_time)
    
    try:
        while True:
            # Check if the process is still running
            if softue_process.poll() is not None:
                logging.warning(f"softUE process terminated unexpectedly with code {softue_process.returncode}")
                # Process died on its own, restart with same parameters as before
                if consecutive_failures >= args.max_failures:
                    softue_process, wait_time = run_softue(reflash=True)
                    consecutive_failures = 0
                else:
                    softue_process, wait_time = run_softue(reflash=False)
                
                # Wait appropriate time before resuming ping checks
                logging.info(f"Waiting {wait_time} seconds before resuming ping checks")
                time.sleep(wait_time)
                continue
                
            # Check connectivity
            if ping_host(args.host):
                if consecutive_failures > 0:
                    logging.info(f"Ping successful after {consecutive_failures} failures, resetting counter")
                    consecutive_failures = 0
                else:
                    logging.debug("Ping successful, connection is stable")
            else:
                consecutive_failures += 1
                logging.warning(f"Ping failed ({consecutive_failures}/{args.max_failures})")
                
                # Only restart if we've reached the threshold
                if consecutive_failures >= args.max_failures:
                    logging.error(f"Reached {args.max_failures} consecutive failures, restarting softUE")
                    
                    # Terminate the current process
                    softue_process.terminate()
                    try:
                        softue_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        logging.warning("Process did not terminate gracefully, killing it")
                        softue_process.kill()
                    
                    # Restart with reflash
                    softue_process, wait_time = run_softue(reflash=True)
                    consecutive_failures = 0
                    
                    # Wait appropriate time before resuming ping checks
                    logging.info(f"Waiting {wait_time} seconds before resuming ping checks")
                    time.sleep(wait_time)
            
            # Wait before next ping check
            time.sleep(args.ping_interval)
                
    except KeyboardInterrupt:
        logging.info("Exiting softUE monitor")
        if softue_process.poll() is None:
            softue_process.terminate()
            try:
                softue_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                softue_process.kill()

if __name__ == "__main__":
    main()
