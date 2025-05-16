from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import mysql.connector
from dotenv import load_dotenv
from functools import wraps
import random
from faker import Faker
from datetime import datetime
import matplotlib
import razorpay
import time

import matplotlib.pyplot as plt
from io import BytesIO
import base64
import json


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
app.config["UPLOAD_FOLDER"] = "uploads"


def get_db_connection():
    """Create and return a new database connection"""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306)),
    )


def initialize_database():
    """Initialize database tables if they don't exist"""
    conn = None
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)

        curr.execute(
            """
            CREATE TABLE IF NOT EXISTS questions(
                day INT,
                question TEXT,
                option_a VARCHAR(255),
                option_b VARCHAR(255),
                option_c VARCHAR(255),
                option_d VARCHAR(255),
                correct_option INT,
                subject VARCHAR(255),
                topic text,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        curr.execute(
            """
            CREATE TABLE IF NOT EXISTS syllabus (
                day INT PRIMARY KEY,
                topic TEXT NOT NULL,
                description TEXT
            )
            """
        )

        curr.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                phone VARCHAR(15) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                category VARCHAR(50) NOT NULL,
                district VARCHAR(50) NOT NULL,
                password VARCHAR(200) NOT NULL,
                subscription bool,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        curr.execute(
            """
        CREATE TABLE IF NOT EXISTS quiz_results (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_email VARCHAR(255) NOT NULL,
            day INT NOT NULL,
            total_score INT NOT NULL,
            total_questions INT NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            attempts INT,
            district VARCHAR(255),
            FOREIGN KEY (user_email) REFERENCES users(email),
            UNIQUE KEY user_day_unique (user_email, day)
        )
        """
        )

        # Create subject_results table exactly as specified
        curr.execute(
            """
        CREATE TABLE IF NOT EXISTS subject_results (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_email VARCHAR(255) NOT NULL,
            day INT NOT NULL,
            subject VARCHAR(255) NOT NULL,
            correct_answers INT NOT NULL,
            total_questions INT NOT NULL,
            percentage INT NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_email) REFERENCES users(email),
            UNIQUE KEY user_day_subject_unique (user_email, day, subject)
        )
        """
        )
        conn.commit()

    except Exception as e:
        print(f"Database initialization error: {str(e)}")
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()


# Initialize database tables
initialize_database()


def login_required(f):
    """Decorator to ensure user is logged in"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            # Store the original URL the user was trying to access
            session["next_url"] = request.url
            flash("You must register or login to access this page", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def populate_syllabus():
    conn = None
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)

        # Check if syllabus is empty
        curr.execute("SELECT COUNT(*) as count FROM syllabus")
        if curr.fetchone()["count"] == 0:
            # Add sample syllabus data
            sample_data = [
                (1, "Introduction to Python", "Basic Python programming concepts"),
                (2, "Data Structures", "Lists, tuples, dictionaries, and sets"),
                (3, "Control Flow", "Conditionals and loops in Python"),
                # Add more days as needed
            ]

            curr.executemany(
                "INSERT INTO syllabus (day, topic, description) VALUES (%s, %s, %s)",
                sample_data,
            )
            conn.commit()
    except Exception as e:
        print(f"Error populating syllabus: {str(e)}")
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()


# Call this function after initialize_database()
populate_syllabus()



razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)


@app.route("/days")
@login_required
def days():
    conn = None
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)

        # Fetch all syllabus days with information about whether questions exist
        curr.execute(
            """
            SELECT s.day, s.topic, s.description, 
                   CASE WHEN q.day IS NOT NULL THEN 1 ELSE 0 END as has_questions
            FROM syllabus s
            LEFT JOIN (
                SELECT DISTINCT day FROM questions
            ) q ON s.day = q.day
            ORDER BY s.day
        """
        )

        syllabus = curr.fetchall()

        return render_template("days.html", syllabus=syllabus)

    except Exception as e:
        flash(f"Error loading days: {str(e)}", "error")
        return redirect(url_for("index"))
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/subscription", methods=["GET", "POST"])
@login_required
def subscription():
    # Check subscription status first
    conn = None
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)
        
        curr.execute(
            "SELECT subscription FROM users WHERE id = %s",
            (session.get("user_id"),)
        )
        user = curr.fetchone()
        has_subscription = user and user.get("subscription")
        
        if request.method == "POST":
            if has_subscription:
                flash("You already have an active subscription!", "info")
                return redirect(url_for("subscription"))
            
            try:
                # Payment processing logic here
                amount = 300 * 100
                currency = "INR"
                receipt = f"sub_{session.get('user_id')}_{int(time.time())}"
                
                razorpay_order = razorpay_client.order.create({
                    "amount": amount,
                    "currency": currency,
                    "receipt": receipt,
                    "payment_capture": 1
                })
                
                session["razorpay_order_id"] = razorpay_order["id"]
                
                return render_template("payment.html",
                    razorpay_key=os.getenv("RAZORPAY_KEY_ID"),
                    order_id=razorpay_order["id"],
                    amount=amount,
                    currency=currency,
                    name=session.get("user_name", "User"),
                    email=session.get("user_email", "")
                )
                
            except Exception as e:
                flash(f"Error creating payment order: {str(e)}", "error")
        
        return render_template("subscription.html", has_subscription=has_subscription)
        
    except Exception as e:
        flash(f"Error checking subscription status: {str(e)}", "error")
        return redirect(url_for("index"))
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()


@app.route("/exams")
def exams():
    conn = None
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)

        # Get distinct days
        curr.execute("SELECT DISTINCT(day) FROM questions ORDER BY day DESC")
        distinct_days = [row["day"] for row in curr.fetchall()]

        # Create a function to get day info that can be called from the template
        def get_day_info(day):
            curr.execute(
                """
                SELECT 
                    topic, 
                    COUNT(*) as question_count 
                FROM questions 
                WHERE day = %s
                GROUP BY topic
                LIMIT 1
            """,
                (day,),
            )
            return curr.fetchone() or {"topic": None, "question_count": 0}

        return render_template(
            "new_exams.html", days=distinct_days, get_day_info=get_day_info
        )
    except Exception as e:
        flash(f"Error loading exams: {str(e)}", "error")
        return redirect(url_for("index"))
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()


@app.route("/quiz/<int:day>")
@login_required
def quiz(day):
    conn = None
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)
        user_email = session.get("user_email")

        # First check subscription status
        curr.execute(
            "SELECT subscription FROM users WHERE email = %s",
            (user_email,)
        )
        user_data = curr.fetchone()
        
        if not user_data:
            flash("User not found", "error")
            return redirect(url_for("index"))
            
        if not user_data.get("subscription"):
            flash("You need a premium subscription to access this content", "warning")
            return redirect(url_for("subscription"))

        # Then check attempts
        curr.execute(
            "SELECT attempts FROM quiz_results WHERE user_email = %s AND day = %s",
            (user_email, day)
        )
        attempt_data = curr.fetchone()
        
        # If no record exists, attempts will be None (0 attempts)
        attempts = attempt_data["attempts"] if attempt_data else 0
        
        if attempts >= 2:
            return render_template("exhaust.html")

        # Fetch questions
        curr.execute(
            """
            SELECT day, question, option_a, option_b, option_c, option_d, 
                   correct_option, subject 
            FROM questions 
            WHERE day = %s
            """,
            (day,),
        )
        questions = curr.fetchall()

        if not questions:
            flash(f"No questions found for Day {day}", "warning")
            return redirect(url_for("exams"))

        return render_template(
            "quiz3.html",
            day=day,
            questions=questions,
            user_id=user_email,
        )

    except Exception as e:
        flash(f"Error loading quiz: {str(e)}", "error")
        return redirect(url_for("exams"))
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()

@app.route("/payment/success", methods=["POST"])
@login_required
def payment_success():
    conn = None
    curr = None
    try:
        # Verify payment signature
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": request.form["razorpay_order_id"],
            "razorpay_payment_id": request.form["razorpay_payment_id"],
            "razorpay_signature": request.form["razorpay_signature"]
        })

        print("Payment signature verified successfully.")

        # Update subscription status in database
        conn = get_db_connection()
        print(f"Database connection established: {conn is not None}")
        if conn:
            curr = conn.cursor()
            print(f"Cursor created: {curr is not None}")

            user_id = session.get("user_id")
            print(f"User ID from session: {user_id}")

            # Set subscription to TRUE (1 in MySQL) for this user
            sql = "UPDATE users SET subscription = TRUE WHERE id = %s"
            print(f"Executing SQL: {sql}, with params: {(user_id,)}")
            curr.execute(sql, (user_id,))
            conn.commit()
            print("Database commit successful.")

            flash("Payment successful! Your subscription has been activated.", "success")
            return redirect(url_for("days"))
        else:
            flash("Failed to connect to the database.", "error")
            return redirect(url_for("subscription")) # Or another appropriate route

    except razorpay.errors.SignatureVerificationError:
        flash("Payment verification failed. Please contact support.", "error")
    except Exception as e:
        flash(f"Error processing payment: {str(e)}", "error")
        print(f"Error in payment_success: {e}") # Log the full exception
    finally:
        if curr: curr.close()
        if conn: conn.close()

    return redirect(url_for("subscription")) # This line might be redundant


@app.route("/user-results")
@login_required
def user_results():
    try:
        user_email = session.get("user_email")

        if not user_email:
            return jsonify({"error": "user_email parameter is required"}), 400

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            if conn is None:
                return jsonify({"error": "Failed to connect to database"}), 500

            cursor = conn.cursor(dictionary=True)

            # Get distinct days attempted by user with their district ranks
            cursor.execute(
                """
                SELECT DISTINCT q.day, 
                       (SELECT COUNT(*) + 1 
                        FROM quiz_results 
                        WHERE day = q.day AND district = q.district AND total_score > q.total_score) as district_rank,
                       (SELECT COUNT(DISTINCT user_email) 
                        FROM quiz_results 
                        WHERE day = q.day AND district = q.district) as total_in_district,
                       q.district
                FROM quiz_results q
                WHERE q.user_email = %s
                ORDER BY q.day DESC
            """,
                (user_email,),
            )

            results = cursor.fetchall()

            if not results:
                return render_template(
                    "user_results.html",
                    user_email=user_email,
                    result_cards=[],
                    message="No quiz attempts found for this user",
                )

            # Prepare simplified data for template
            result_cards = []
            for result in results:
                result_cards.append(
                    {
                        "day": result["day"],
                        "district_rank": result["district_rank"],
                        "total_in_district": result["total_in_district"],
                        "district": result["district"],
                    }
                )

            return render_template(
                "user_results.html", user_email=user_email, result_cards=result_cards
            )

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    except Exception as e:
        app.logger.error(f"Error in user_results: {str(e)}")
        return jsonify({"error": "Server error", "details": str(e)}), 500


@app.route("/quiz-sample")
@login_required
def quiz1():
    conn = None
    day = 0
    curr = None
    try:
        conn = get_db_connection()
        curr = conn.cursor(dictionary=True)

        # Fetch questions with subject field
        curr.execute(
            """
            SELECT day, question, option_a, option_b, option_c, option_d, 
                   correct_option, subject 
            FROM sample
            WHERE day = %s
        """,
            (0,),
        )

        questions = curr.fetchall()

        if not questions:
            flash(f"No questions found for Day {day}", "warning")
            return redirect(url_for("exams"))

        # Get user ID from session - ensure this matches your login system
        user_email = session.get("user_email")

        if not user_email:
            flash("User not authenticated", "error")
            return redirect(url_for("login"))

        print(questions)

        return render_template(
            "quiz3.html",
            day=0,
            questions=questions,
            user_id=user_email,  # Pass as integer
        )

    except Exception as e:
        flash(f"Error loading quiz: {str(e)}", "error")
        return redirect(url_for("exams"))
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()


# ending


@app.route("/submit-quiz", methods=["POST"])
def submit_quiz():
    data = request.get_json()
    user_id = session.get("user_id")
    data["user_email"] = data["user_id"]
    required_fields = [
        "user_email",
        "day",
        "total_score",
        "total_questions",
        "subject_scores",
    ]
    if not all(key in data for key in required_fields):
        return (
            jsonify({"error": f"Missing required fields. Required: {required_fields}"}),
            400,
        )

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Start transaction
        conn.start_transaction()

        # 1. First get the user's district from users table
        cursor.execute(
            """
        SELECT district FROM users WHERE email = %s
        """,
            (data["user_email"],),
        )
        user_data = cursor.fetchone()

        if not user_data or "district" not in user_data:
            return jsonify({"error": "User district not found"}), 400

        district = user_data["district"]

        # 2. Ensure user exists (for foreign key constraint)
        cursor.execute(
            "INSERT IGNORE INTO users (email, district) VALUES (%s, %s) ON DUPLICATE KEY UPDATE district = %s",
            (data["user_email"], district, district),
        )

        # 3. Check if a record already exists for this user and day
        cursor.execute(
            """
        SELECT id, attempts FROM quiz_results 
        WHERE user_email = %s AND day = %s
        FOR UPDATE
        """,
            (data["user_email"], data["day"]),
        )
        existing_quiz = cursor.fetchone()

        if existing_quiz:
            # Update existing record
            new_attempts = existing_quiz["attempts"] + 1
            cursor.execute(
                """
            UPDATE quiz_results 
            SET total_score = %s, 
                total_questions = %s, 
                attempts = %s,
                district = %s,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
                (
                    data["total_score"],
                    data["total_questions"],
                    new_attempts,
                    district,  # Update district
                    existing_quiz["id"],
                ),
            )
            quiz_result_id = existing_quiz["id"]

            # Update subject results
            for subject, scores in data["subject_scores"].items():
                cursor.execute(
                    """
                INSERT INTO subject_results
                (user_email, day, subject, correct_answers, total_questions, percentage)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    correct_answers = VALUES(correct_answers),
                    total_questions = VALUES(total_questions),
                    percentage = VALUES(percentage),
                    completed_at = CURRENT_TIMESTAMP
                """,
                    (
                        data["user_email"],
                        data["day"],
                        subject,
                        scores["correct"],
                        scores["total"],
                        scores["percentage"],
                    ),
                )
        else:
            # Insert new record with district
            cursor.execute(
                """
            INSERT INTO quiz_results 
            (user_email, day, total_score, total_questions, attempts, district)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    data["user_email"],
                    data["day"],
                    data["total_score"],
                    data["total_questions"],
                    data.get("attempts", 1),
                    district,  # Include district
                ),
            )
            quiz_result_id = cursor.lastrowid

            # Insert subject results
            for subject, scores in data["subject_scores"].items():
                cursor.execute(
                    """
                INSERT INTO subject_results
                (user_email, day, subject, correct_answers, total_questions, percentage)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    (
                        data["user_email"],
                        data["day"],
                        subject,
                        scores["correct"],
                        scores["total"],
                        scores["percentage"],
                    ),
                )

        # Commit transaction
        conn.commit()
        return (
            jsonify(
                {
                    "success": True,
                    "quiz_result_id": quiz_result_id,
                    "action": "updated" if existing_quiz else "inserted",
                    "attempts": (
                        new_attempts if existing_quiz else data.get("attempts", 1)
                    ),
                    "district": district,  # Return district in response
                }
            ),
            201,
        )

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error saving quiz results: {e}")
        return jsonify({"error": "Failed to save quiz results", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        category = request.form.get("category", "").strip()
        district = request.form.get("district", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not all(
            [name, phone, email, category, district, password, confirm_password]
        ):
            flash("All fields are required", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for("register"))

        conn = None
        curr = None
        try:
            conn = get_db_connection()
            curr = conn.cursor(dictionary=True)

            # Check if email exists
            curr.execute("SELECT id FROM users WHERE email = %s", (email,))
            if curr.fetchone():
                flash("Email already registered. Please login.", "error")
                return redirect(url_for("register"))

            # Hash password and insert
            hashed_password = generate_password_hash(password)
            curr.execute(
                """INSERT INTO users (name, phone, email, category, district, password)
                VALUES (%s, %s, %s, %s, %s, %s)""",
                (name, phone, email, category, district, hashed_password),
            )
            conn.commit()

            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))

        except Exception as e:
            flash(f"Registration error: {str(e)}", "error")
            return redirect(url_for("register"))
        finally:
            if curr:
                curr.close()
            if conn:
                conn.close()

    return render_template("registration.html")


@app.route("/add-question", methods=["GET", "POST"])
def addQuestions():
    if request.method == "POST":
        day = request.form.get("day1", "").strip()
        question = request.form.get("question_text", "").strip()
        optionA = request.form.get("option_a", "").strip()
        optionB = request.form.get("option_b", "").strip()
        optionC = request.form.get("option_c", "").strip()
        optionD = request.form.get("option_d", "").strip()
        correct_option = request.form.get("correct_option", "").strip()
        subject = request.form.get("subject", "").strip()
        topic = request.form.get("topic", "").strip()

        if not all(
            [
                day,
                question,
                optionA,
                optionB,
                optionC,
                optionD,
                correct_option,
                subject,
                topic,
            ]
        ):
            flash("All fields are required", "error")
            return redirect(url_for("addQuestions"))

        conn = None
        curr = None
        try:
            conn = get_db_connection()
            curr = conn.cursor()

            curr.execute(
                """INSERT INTO questions 
                (day, question, option_a, option_b, option_c, option_d, correct_option, subject,topic)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,%s)""",
                (
                    day,
                    question,
                    optionA,
                    optionB,
                    optionC,
                    optionD,
                    correct_option,
                    subject,
                    topic,
                ),
            )
            conn.commit()

            flash("Question added successfully", "success")
            return redirect(url_for("addQuestions"))

        except Exception as e:
            flash(f"Error adding question: {str(e)}", "error")
            return redirect(url_for("addQuestions"))
        finally:
            if curr:
                curr.close()
            if conn:
                conn.close()

    return render_template("final_question_adding.html")


# adding sample_questions
@app.route("/add-question-sample", methods=["GET", "POST"])
def addQuestions1():
    if request.method == "POST":
        day = request.form.get("day1", "").strip()
        question = request.form.get("question_text", "").strip()
        optionA = request.form.get("option_a", "").strip()
        optionB = request.form.get("option_b", "").strip()
        optionC = request.form.get("option_c", "").strip()
        optionD = request.form.get("option_d", "").strip()
        correct_option = request.form.get("correct_option", "").strip()
        subject = request.form.get("subject", "").strip()

        if not all(
            [day, question, optionA, optionB, optionC, optionD, correct_option, subject]
        ):
            flash("All fields are required", "error")
            return redirect(url_for("addQuestions"))

        conn = None
        curr = None
        try:
            conn = get_db_connection()
            curr = conn.cursor()

            curr.execute(
                """INSERT INTO sample
                (day, question, option_a, option_b, option_c, option_d, correct_option, subject)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    day,
                    question,
                    optionA,
                    optionB,
                    optionC,
                    optionD,
                    correct_option,
                    subject,
                ),
            )
            conn.commit()

            flash("Question added successfully", "success")
            return redirect(url_for("addQuestions1"))

        except Exception as e:
            flash(f"Error adding question: {str(e)}", "error")
            return redirect(url_for("addQuestions1"))
        finally:
            if curr:
                curr.close()
            if conn:
                conn.close()

    return render_template("sample_test.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        conn = None
        curr = None
        try:
            conn = get_db_connection()
            curr = conn.cursor(dictionary=True)

            curr.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = curr.fetchone()

            if user and check_password_hash(user["password"], password):
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_email"] = user["email"]
                flash("Login successful", "success")

                # Redirect to the originally requested URL if it exists
                next_url = session.pop("next_url", None)
                return redirect(next_url or url_for("exams"))
            else:
                flash("Invalid email or password", "error")

        except Exception as e:
            flash(f"Login error: {str(e)}", "error")
        finally:
            if curr:
                curr.close()
            if conn:
                conn.close()

    return render_template("login_final.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("login"))


@app.route("/score-board")
def score_board():
    try:
        user_email = request.args.get("user_id")
        day = request.args.get("day")

        if not user_email or not day:
            return (
                jsonify({"error": "Both user_id and day parameters are required"}),
                400,
            )

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            if conn is None:
                return (
                    jsonify({"error": "Failed to connect to the database"}),
                    500,
                )
            cursor = conn.cursor(dictionary=True)

            # Main quiz results query
            cursor.execute(
                """
                SELECT q.*, u.`name` as `student_name`, u.`district`
                FROM `quiz_results` q
                JOIN `users` u ON q.`user_email` = u.`email`
                WHERE q.`user_email` = %s AND q.`day` = %s
            """,
                (user_email, day),
            )
            quiz_data = cursor.fetchone()

            if not quiz_data:
                return (
                    jsonify(
                        {
                            "error": f"No quiz results found for user {user_email} on day {day}"
                        }
                    ),
                    404,
                )

            # Subject scores query
            cursor.execute(
                """
                SELECT `subject`, `correct_answers`, `total_questions`, `percentage`
                FROM `subject_results`
                WHERE `user_email` = %s AND `day` = %s
            """,
                (user_email, day),
            )

            subject_scores = {}
            for row in cursor.fetchall():
                subject_scores[row["subject"]] = {
                    "correct": row["correct_answers"],
                    "total": row["total_questions"],
                    "percentage": row["percentage"],
                }

            # District rank query
            cursor.execute(
                """
                SELECT COUNT(*) + 1 as `rank`
                FROM `quiz_results`
                WHERE `day` = %s AND `district` = %s AND `total_score` > (
                    SELECT `total_score` FROM `quiz_results`
                    WHERE `user_email` = %s AND `day` = %s
                )
            """,
                (day, quiz_data["district"], user_email, day),
            )

            district_rank_result = cursor.fetchone()
            district_rank = district_rank_result["rank"] if district_rank_result else 1

            # District members attempted query
            cursor.execute(
                """
                SELECT COUNT(DISTINCT `user_email`) as `total`
                FROM `quiz_results`
                WHERE `day` = %s AND `district` = %s
            """,
                (day, quiz_data["district"]),
            )

            total_members_attempted = cursor.fetchone()["total"]

            # District average query
            cursor.execute(
                """
                SELECT COALESCE(AVG(`total_score`), 0) AS `avg_score`
                FROM `quiz_results`
                WHERE `day` = %s AND `district` = %s
            """,
                (day, quiz_data["district"]),
            )

            district_avg_result = cursor.fetchone()
            district_average = round(float(district_avg_result["avg_score"]), 2)

            # State average query
            cursor.execute(
                """
                SELECT COALESCE(AVG(`total_score`), 0) AS `avg_score`
                FROM `quiz_results`
                WHERE `day` = %s
            """,
                (day,),
            )

            state_avg_result = cursor.fetchone()
            state_average = round(float(state_avg_result["avg_score"]), 2)

            performance_data = {
                "user_id": user_email,
                "day": day,
                "student_name": quiz_data.get("student_name", "Test Student"),
                "total_score": quiz_data["total_score"],
                "total_questions": quiz_data["total_questions"],
                "subjects": subject_scores,
                "district": quiz_data["district"],
                "district_rank": district_rank,
                "total_members_attempted": total_members_attempted,
                "district_average": district_average,
                "state_average": state_average,
                "date_completed": (
                    quiz_data["completed_at"].strftime("%Y-%m-%d")
                    if quiz_data["completed_at"]
                    else None
                ),
            }
            print(performance_data)

            return render_template("score-board.html", data=performance_data)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    except Exception as e:
        app.logger.error(f"Application error: {str(e)}")
        return jsonify({"error": "Server error", "details": str(e)}), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
