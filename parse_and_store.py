import pdfplumber
import sqlite3
import re
import argparse
import os
import json

DB_FILE = "questions.db"
PDF_FILE = "人工智能导论-习题汇总-v6(1).pdf"

def create_tables(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS questions")
    cursor.execute("DROP TABLE IF EXISTS user_stats")
    cursor.execute("DROP TABLE IF EXISTS quiz_sessions")
    cursor.execute("DROP TABLE IF EXISTS options")
    cursor.execute("""
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            options TEXT NOT NULL,
            answer TEXT NOT NULL,
            is_multiple_choice INTEGER DEFAULT 0,
            explanation TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE user_stats (
            question_id INTEGER PRIMARY KEY,
            total_attempts INTEGER DEFAULT 0,
            wrong_attempts INTEGER DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE quiz_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            question_id INTEGER,
            is_correct INTEGER,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    """)
    conn.commit()

def extract_text_from_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    return full_text

def extract_options(block_before_answer):
    """Extract all options from a question block. Returns dict of {letter: text}."""
    options = {}

    pattern = re.compile(
        r'(?:^|\n|\s)([A-Z])\.\s*'
        r'(.*?)'
        r'(?=(?:\n|\s)[A-Z]\.|答案|$)',
        re.DOTALL
    )
    matches = list(pattern.finditer(block_before_answer))

    for m in matches:
        letter = m.group(1)
        text = m.group(2).strip()
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        if letter not in options:
            options[letter] = text
    return options

def extract_question_text(block, options_dict):
    """Extract question text by removing option markers from the block."""
    text = block
    for letter in sorted(options_dict.keys()):
        patterns = [
            re.compile(r'\n' + re.escape(letter) + r'\.\s*'),
            re.compile(re.escape(letter) + r'\.\s*'),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                text = text[:m.start()]
                break
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text

def parse_answer_string(answer_raw, available_options):
    """Parse answer like 'A、B、D' or 'A,B,D' or 'A' into sorted string 'ABD'.
    Returns (answer_string, is_multiple_choice)."""
    answer_raw = answer_raw.strip()
    letters = re.findall(r'[A-Z]', answer_raw)
    valid_letters = sorted([l for l in letters if l in available_options])

    if not valid_letters:
        return None, False

    return ''.join(valid_letters), len(valid_letters) > 1

def parse_questions(text):
    questions = []
    log = []

    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if re.match(r"^\d+$", line):
            continue
        cleaned_lines.append(line)
    full_text = "\n".join(cleaned_lines)

    question_starts = list(re.finditer(r'(\d+)\.\s+', full_text))

    for i, start_match in enumerate(question_starts):
        q_id = int(start_match.group(1))
        start_pos = start_match.end()

        if i + 1 < len(question_starts):
            end_pos = question_starts[i + 1].start()
        else:
            end_pos = len(full_text)

        block = full_text[start_pos:end_pos]

        is_mc = "（多选题）" in block

        answer_match = re.search(r'答案[：:]\s*([A-Z][A-Z、,，\s]*)', block)
        if not answer_match:
            log.append({"id": q_id, "status": "skipped", "reasons": ["no answer found"]})
            continue

        answer_raw = answer_match.group(1)
        block_before_answer = block[:answer_match.start()]

        options = extract_options(block_before_answer)

        if not options:
            log.append({"id": q_id, "status": "skipped", "reasons": ["no options found"]})
            continue

        if "A" not in options:
            log.append({"id": q_id, "status": "skipped", "reasons": ["missing option A"]})
            continue

        for letter, text in list(options.items()):
            if re.match(r"^\d+\.", text):
                del options[letter]

        if not options or "A" not in options:
            log.append({"id": q_id, "status": "skipped", "reasons": ["options invalidated after cleanup"]})
            continue

        answer, is_multiple = parse_answer_string(answer_raw, options)

        if answer is None:
            log.append({"id": q_id, "status": "skipped", "reasons": [f"cannot parse answer: {answer_raw}"]})
            continue

        if is_mc and not is_multiple:
            pass

        question_text = extract_question_text(block_before_answer, options)

        if not question_text:
            log.append({"id": q_id, "status": "skipped", "reasons": ["empty question text"]})
            continue

        question_text = question_text.replace("答案", "").strip()
        question_text = question_text.replace("（多选题）", "").strip()
        question_text = re.sub(r'\s+', ' ', question_text)

        questions.append({
            "id": q_id,
            "text": question_text,
            "options": options,
            "answer": answer,
            "is_multiple_choice": is_multiple,
            "explanation": ""
        })

    return questions, log

def save_to_db(questions, conn):
    cursor = conn.cursor()
    inserted = 0
    for q in questions:
        options_json = json.dumps(q["options"], ensure_ascii=False)
        cursor.execute("""
            INSERT INTO questions (id, text, options, answer, is_multiple_choice, explanation)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (q["id"], q["text"], options_json, q["answer"], 
              1 if q["is_multiple_choice"] else 0, q["explanation"]))
        cursor.execute("""
            INSERT OR IGNORE INTO user_stats (question_id, total_attempts, wrong_attempts)
            VALUES (?, 0, 0)
        """, (q["id"],))
        inserted += 1
    conn.commit()
    return inserted, 0

def main():
    parser = argparse.ArgumentParser(description="Parse PDF questions and store in SQLite database.")
    parser.add_argument("--pdf", type=str, default=PDF_FILE, help="Path to PDF file")
    parser.add_argument("--db", type=str, default=DB_FILE, help="Path to SQLite database")
    parser.add_argument("--log", type=str, default="parse_log.json", help="Path to parse log file")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"Error: PDF file not found: {args.pdf}")
        return

    print(f"Extracting text from {args.pdf}...")
    text = extract_text_from_pdf(args.pdf)
    print(f"Extracted {len(text)} characters.")

    print("Parsing questions...")
    questions, log = parse_questions(text)
    print(f"Parsed {len(questions)} valid questions.")

    mc_count = sum(1 for q in questions if q["is_multiple_choice"])
    print(f"Multiple choice: {mc_count}, Single choice: {len(questions) - mc_count}")

    if log:
        print(f"Skipped {len(log)} questions with issues:")
        for entry in log:
            print(f"  Q{entry['id']}: {', '.join(entry['reasons'])}")
        with open(args.log, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(f"Parse log saved to {args.log}")

    if not questions:
        print("No valid questions found. Exiting.")
        return

    conn = sqlite3.connect(args.db)
    create_tables(conn)

    print(f"Saving to database {args.db}...")
    inserted, updated = save_to_db(questions, conn)
    print(f"Inserted: {inserted}, Updated: {updated}")

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM questions")
    total = cursor.fetchone()[0]
    print(f"Total questions in database: {total}")

    conn.close()
    print("Done!")

if __name__ == "__main__":
    main()
