import os
import logging

class Logger:
    def __init__(self, log_file_name: str, recreate_file: bool = True):
        """Initialize logger with file in same directory as the script"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_file_path = os.path.join(script_dir, log_file_name)
        
        if recreate_file and os.path.exists(self.log_file_path):
            os.remove(self.log_file_path)
        
        # Create a unique logger name based on the log file name
        logger_name = f"logger_{log_file_name.replace('.', '_').replace('-', '_')}"
        self.logger = logging.getLogger(logger_name)
        
        # Remove any existing handlers to avoid duplicates
        self.logger.handlers.clear()
        
        # Set the logger level
        self.logger.setLevel(logging.INFO)
        
        # Create file handler for this specific logger
        file_handler = logging.FileHandler(self.log_file_path)
        file_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(file_handler)
        
        # Prevent propagation to root logger to avoid duplicate logs
        self.logger.propagate = False
    
    def info(self, message: str) -> None:
        self.logger.info(message)
    
    def error(self, message: str) -> None:
        self.logger.error(message)
    
    def warning(self, message: str) -> None:
        self.logger.warning(message)
