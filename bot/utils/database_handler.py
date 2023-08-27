import psycopg2
import time
from typing import Dict, Any

class DatabaseHandler:
    def __init__(self, db_params: Dict[str, Any]):
        self.conn = psycopg2.connect(**db_params)
        self.ensure_tables_exist()
        # Define the mapping for vote_ids to column names
        self.vote_options = {
            1: 'aye',
            2: 'nay',
            3: 'recuse',
            4: 'abstain'
        }
        
    def fetch_vote_counts_from_db(self, message_id: str):
        with self.conn.cursor() as cursor:
            cursor.execute("""
                SELECT aye, nay, recuse 
                FROM referenda_thread 
                WHERE thread_id = %s;
            """, (message_id,))
            result = cursor.fetchone()
            if result:
                return result
            else:
                return 0, 0, 0


    # Updated save_or_update_vote method to ensure that the thread_id exists in the referenda_thread table before inserting into users.
    def save_or_update_vote(self, referenda_id: str, user_id: str, vote_id: int, username: str):
        with self.conn.cursor() as cursor:
            try:
                # Ensure thread_id exists in referenda_thread
                cursor.execute("SELECT 1 FROM referenda_thread WHERE thread_id = %s;", (referenda_id,))
                if cursor.fetchone() is None:
                    cursor.execute("""
                        INSERT INTO referenda_thread (thread_id, aye, nay, recuse, abstain, epoch)
                        VALUES (%s, 0, 0, 0, 0, %s);
                    """, (referenda_id, int(time.time())))
                
                # Check if the user has already voted
                cursor.execute("SELECT vote_type FROM users WHERE user_id = %s AND thread_id = %s;", (str(user_id), str(referenda_id)))
                previous_vote = cursor.fetchone()
                already_voted = bool(previous_vote)

                if already_voted:
                    previous_vote = previous_vote[0]
                    if previous_vote != vote_id:
                        # Update counts based on new and old votes
                        cursor.execute("UPDATE referenda_thread SET {} = {} - 1 WHERE thread_id = %s;".format(self.vote_options[previous_vote], self.vote_options[previous_vote]), (str(referenda_id),))
                        cursor.execute("UPDATE referenda_thread SET {} = {} + 1 WHERE thread_id = %s;".format(self.vote_options[vote_id], self.vote_options[vote_id]), (str(referenda_id),))

                    # Update user's vote
                    cursor.execute("UPDATE users SET username = %s, vote_type = %s WHERE user_id = %s AND thread_id = %s;", (username, vote_id, str(user_id), str(referenda_id)))
                else:
                    # Increment new vote count
                    cursor.execute("UPDATE referenda_thread SET {} = {} + 1 WHERE thread_id = %s;".format(self.vote_options[vote_id], self.vote_options[vote_id]), (str(referenda_id),))
                    
                    # Insert new user's vote
                    cursor.execute("INSERT INTO users (user_id, username, vote_type, thread_id) VALUES (%s, %s, %s, %s);", (str(user_id), username, vote_id, str(referenda_id)))

            except Exception as e:
                self.conn.rollback()
                raise e

        self.conn.commit()
        return already_voted, previous_vote


    def ensure_tables_exist(self):
        with self.conn.cursor() as cursor:
            # Create vote_options table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vote_options (
                    vote_id INT PRIMARY KEY,
                    description TEXT
                );
            """)

            # Insert default vote options if table is empty
            cursor.execute("SELECT COUNT(*) FROM vote_options;")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO vote_options (vote_id, description) VALUES
                    (1, 'aye'),
                    (2, 'nay'),
                    (3, 'recuse'),
                    (4, 'abstain');
                """)

            # Create referenda_thread table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS referenda_thread (
                    thread_id TEXT PRIMARY KEY,
                    aye INT,
                    nay INT,
                    recuse INT,
                    abstain INT,
                    epoch INT,
                    archive_bit BOOLEAN DEFAULT FALSE
                );
            """)

            # Create users table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT,
                    username TEXT,
                    vote_type INT,
                    thread_id TEXT,
                    FOREIGN KEY(thread_id) REFERENCES referenda_thread(thread_id),
                    FOREIGN KEY(vote_type) REFERENCES vote_options(vote_id)
                );
            """)

            self.conn.commit()


            
        # Need to fix this
   #def archive_referenda(self, days=14):
   #    current_time = int(time.time())
   #    time_threshold = days * 24 * 60 * 60  # Convert days to seconds

   #    with self.conn.cursor() as cursor:
   #        query = """UPDATE referenda SET archive_bit = TRUE
   #                   WHERE %s - epoch > %s;"""
   #        cursor.execute(query, (current_time, time_threshold))
   #        self.conn.commit()