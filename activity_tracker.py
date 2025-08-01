import logging
from datetime import datetime

# Configure logger for activity tracking
logger = logging.getLogger(__name__)

class ActivityTracker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def record_bot_usage(self, service_id: str, user_id: int, service_name: str):
        """
        Records bot usage activity
        
        Args:
            service_id (str): Service identifier from render
            user_id (int): Telegram user ID
            service_name (str): Name of the bot service
        """
        try:
            timestamp = datetime.utcnow().isoformat()
            log_message = f"Bot Usage - Service: {service_name} ({service_id}), User: {user_id}, Time: {timestamp}"
            self.logger.info(log_message)
            
            # You can extend this to save to database, send to external service, etc.
            # For now, it just logs the activity
            
        except Exception as e:
            self.logger.error(f"Error recording bot usage: {e}")

# Create a global instance
activity_tracker = ActivityTracker()