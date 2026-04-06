import re

from flask import Flask, render_template, request, jsonify , session , redirect
import sqlite3
import requests
import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY")
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

def evaluate_answer(question, answer):

    prompt = f"""
    Evaluate the following answer.

    Question: {question}
    Answer: {answer}

    Give:
    1. Score out of 10
    2. Short feedback

    Format:
    Score: X/10
    Feedback: ...
    """

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "Assessly App"
        },
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
    )

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except:
        print("Evaluation Error:", response.text)
        return "Score: 0/10\nFeedback: Error evaluating answer"


def generate_question_from_openrouter(domain, previous_questions):

    prompt = f"""
    You are a professional interviewer.

    Domain: {domain}

    Previously asked questions:
    {previous_questions}

    Rules:
    - Do NOT repeat any question
    - Do NOT rephrase previous questions
    - Ask a completely new question from a different topic
    - Ask only ONE question

    Output only the question.
    """

    response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Assessly App"
    },
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
    )

    try:
        print("STATUS:", response.status_code)
        print("RESPONSE:", response.text)

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        print("ERROR:", e)
        print("FULL RESPONSE:", response.text)
        return "Error generating question"




#  Create DB + Tables
def init_db():
    conn = sqlite3.connect("interview.db")
    cursor = conn.cursor()

    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT
        )
    """)


    # Session table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interview_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT
        )
    """)

    # Questions & Answers table


    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        question TEXT,
        answer TEXT,
        score INTEGER,
        feedback TEXT
    )
""")



    conn.commit()
    conn.close()


@app.route("/")
def home():
    if "user" in session:
        return redirect("/profile")
    return redirect("/login")


# Signup Page
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        conn = sqlite3.connect("interview.db")
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, password)
            )
            conn.commit()
            session["user"] = {"username": name, "email": email}
            return redirect("/profile")
        except:
            return "Email already exists!"
        finally:
            conn.close()
    return render_template("signup.html")


#  Login Page
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = sqlite3.connect("interview.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email=? AND password=?",
            (email, password)
        )
        user = cursor.fetchone()
        conn.close()

        if user:
            session["user"] = {"username": user[1], "email": user[2]}
            return redirect("/profile")
        else:
            return "Invalid credentials!"
    return render_template("login.html")


#  Profile Page
@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")
    return render_template("profile.html", user=session["user"])

#  Logout 
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


@app.route("/index")
def index():
    if "user" not in session:
        return redirect("/login")
    return render_template("index.html")


#  Start Interview
@app.route("/chat", methods=["POST"])
def chat():

    #  LOGIN CHECK (IMPORTANT)
    if "user" not in session:
        return redirect("/login")
    
    domain = request.form.get("domain")

    conn = sqlite3.connect("interview.db")
    cursor = conn.cursor()

    # Create new session
    cursor.execute(
        "INSERT INTO interview_sessions (domain) VALUES (?)",
        (domain,)
    )

    conn.commit()

    # Get latest session_id
    session_id = cursor.lastrowid

    conn.close()

    return render_template("chat.html", session_id=session_id)





# Ask Route (MULTIPLE Q LOGIC)
@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    user_message = data.get("message")
    session_id = data.get("session_id")

    conn = sqlite3.connect("interview.db")
    cursor = conn.cursor()

    #  Get all Q&A of this session
    cursor.execute(
        "SELECT * FROM questions_answers WHERE session_id = ?",
        (session_id,)
    )
    rows = cursor.fetchall()

    count = len(rows)

    print("COUNT:", count)

    #  FIRST TIME (no question yet)
    if count == 0:
        #  Get domain
        cursor.execute(
            "SELECT domain FROM interview_sessions WHERE session_id = ?",
            (session_id,)
        )
        domain = cursor.fetchone()[0]

        #  openrouter question
        previous_questions = ""
        question = generate_question_from_openrouter(domain, previous_questions)

        cursor.execute(
            "INSERT INTO questions_answers (session_id, question, answer, score, feedback) VALUES (?, ?, ?, ?, ?)",
            (session_id, question, "", None, None)
        )

        conn.commit()
        conn.close()

        return jsonify({"reply": question})

    #  STORE ANSWER
    elif rows[-1][3] == "" or rows[-1][3] is None:
        #  Get last question
        last_question = rows[-1][2]

        #  Evaluate answer using AI
        evaluation = evaluate_answer(last_question, user_message)

        

    # Extract score & feedback (robust)
        score = 0
        feedback = evaluation

    # Extract first number from response
        match = re.search(r'\d+', evaluation)
        if match:
            score = int(match.group())

    # Extract feedback safely
        if "Feedback:" in evaluation:
            feedback = evaluation.split("Feedback:")[1].strip()

    #  Update DB with answer + score + feedback
        cursor.execute(
            "UPDATE questions_answers SET answer = ?, score = ?, feedback = ? WHERE id = ?",
            (user_message, score, feedback, rows[-1][0])
        )

        conn.commit()

        count += 1

        #  ASK NEXT QUESTION
        if count < 6:
            # Get domain again
            cursor.execute(
                "SELECT domain FROM interview_sessions WHERE session_id = ?",
                (session_id,)
            )
            domain = cursor.fetchone()[0]

            #  Get previous questions
            cursor.execute(
                "SELECT question FROM questions_answers WHERE session_id = ?",
                (session_id,)
            )
            prev_qs = cursor.fetchall()

            previous_questions = "\n".join([q[0] for q in prev_qs])

            #  Generate new question with memory
            question = generate_question_from_openrouter(domain, previous_questions)


            cursor.execute(
                "INSERT INTO questions_answers (session_id, question, answer, score, feedback) VALUES (?, ?, ?, ?, ?)",
                (session_id, question, "",None, None)
            )

            conn.commit()
            conn.close()

            return jsonify({"reply": question})

        else:
            conn.close()
            return jsonify({
                "reply": "Interview Completed ✅",
                "redirect": f"/report/{session_id}"
            })

    else:
        conn.close()
        return jsonify({"reply": "Please answer properly."})
    
@app.route("/report/<int:session_id>")
def report(session_id):
    conn = sqlite3.connect("interview.db")
    cursor = conn.cursor()

    # Get all Q&A
    cursor.execute(
        "SELECT question, answer, score, feedback FROM questions_answers WHERE session_id = ?",
        (session_id,)
    )
    data = cursor.fetchall()

    # Get domain name
    cursor.execute("SELECT domain FROM interview_sessions WHERE session_id = ?", (session_id,))
    domain_name = cursor.fetchone()[0]

    conn.close()

    # Calculate total score
    total_score = 0
    max_score = len(data) * 10

    strengths = []
    weaknesses = []

    for row in data:
        score = row[2] if row[2] else 0
        total_score += score

        if score >= 7:
            strengths.append(row[0])
        elif score <= 5:
            weaknesses.append(row[0])

    percentage = int((total_score / max_score) * 100) if max_score > 0 else 0

    return render_template(
        "report.html",
        data=data,
        total_score=total_score,
        max_score=max_score,
        percentage=percentage,
        strengths=strengths,
        weaknesses=weaknesses,
        domain_name=domain_name
    )


#  Run App
if __name__ == "__main__":
    init_db()
    app.run(debug=True)