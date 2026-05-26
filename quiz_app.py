import sqlite3
import random
import os
import sys
import json
from datetime import datetime

DB_FILE = "questions.db"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_db_connection():
    if not os.path.exists(DB_FILE):
        print(f"Database not found: {DB_FILE}")
        print("Please run parse_and_store.py first.")
        sys.exit(1)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def load_question(row):
    question = dict(row)
    question["options"] = json.loads(question["options"])
    return question

def get_question_count(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM questions")
    return cursor.fetchone()[0]

def get_all_questions(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions ORDER BY id")
    return [load_question(row) for row in cursor.fetchall()]

def get_question_by_id(conn, question_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    if row:
        return load_question(row)
    return None

def get_user_stats(conn, question_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_stats WHERE question_id = ?", (question_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO user_stats (question_id) VALUES (?)", (question_id,))
        conn.commit()
        return cursor.execute("SELECT * FROM user_stats WHERE question_id = ?", (question_id,)).fetchone()
    return row

def update_stats(conn, question_id, is_correct):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_stats SET
            total_attempts = total_attempts + 1,
            wrong_attempts = wrong_attempts + ?
        WHERE question_id = ?
    """, (0 if is_correct else 1, question_id))
    cursor.execute("""
        INSERT INTO quiz_sessions (question_id, is_correct)
        VALUES (?, ?)
    """, (question_id, 1 if is_correct else 0))
    conn.commit()

def shuffle_options(question):
    options_dict = question["options"]
    correct_answer = question["answer"]

    option_letters = sorted(options_dict.keys())
    option_texts = [options_dict[l] for l in option_letters]

    combined = list(zip(option_texts, option_letters))
    random.shuffle(combined)
    shuffled_texts, shuffled_letters = zip(*combined)

    display_map = {}
    display_to_orig = {}
    for i, (opt_text, orig_letter) in enumerate(zip(shuffled_texts, shuffled_letters)):
        display_letter = chr(ord("A") + i)
        display_map[display_letter] = opt_text
        display_to_orig[display_letter] = orig_letter

    if len(correct_answer) == 1:
        new_correct = ""
        for disp_letter, orig_letter in display_to_orig.items():
            if orig_letter == correct_answer:
                new_correct = disp_letter
                break
        return list(shuffled_texts), new_correct, display_map, display_to_orig, False
    else:
        new_correct_list = []
        for disp_letter, orig_letter in display_to_orig.items():
            if orig_letter in correct_answer:
                new_correct_list.append(disp_letter)
        new_correct_list.sort()
        new_correct = ''.join(new_correct_list)
        return list(shuffled_texts), new_correct, display_map, display_to_orig, True

def display_question(question, shuffled_options):
    tag = "（多选题）" if question["is_multiple_choice"] else ""
    print(f"\n{'='*60}")
    print(f"题目 {question['id']}{tag}: {question['text']}")
    print(f"{'='*60}")

    for i, opt in enumerate(shuffled_options):
        letter = chr(ord("A") + i)
        print(f"  {letter}. {opt}")
    print()

def parse_user_input(user_input, num_options):
    user_input = user_input.strip()

    if user_input.upper() == "Q":
        return "Q", False

    separators = [',', '，', '/', ' ', ';', '；', '、']
    for sep in separators:
        if sep in user_input:
            parts = user_input.split(sep)
            cleaned = [p.strip().lower() for p in parts if p.strip()]

            single_map = {}
            for i in range(num_options):
                letter = chr(ord("a") + i)
                single_map[letter] = chr(ord("A") + i)

            result = []
            for part in cleaned:
                if part in single_map:
                    result.append(single_map[part])
                else:
                    try:
                        idx = int(part) - 1
                        if 0 <= idx < num_options:
                            result.append(chr(ord("A") + idx))
                    except ValueError:
                        pass

            if result:
                result_sorted = sorted(set(result))
                return ''.join(result_sorted), True

    lower_input = user_input.lower()

    single_map = {}
    for i in range(num_options):
        letter = chr(ord("a") + i)
        single_map[letter] = chr(ord("A") + i)

    if lower_input in single_map:
        return single_map[lower_input], False

    try:
        idx = int(lower_input) - 1
        if 0 <= idx < num_options:
            return chr(ord("A") + idx), False
    except ValueError:
        pass

    return None, False

def build_input_hint(num_options, is_multiple):
    letters = [chr(ord("A") + i) for i in range(num_options)]
    nums = [str(i + 1) for i in range(num_options)]

    if is_multiple:
        return f"多选用 {','.join(letters[:3])} 或 {','.join(nums[:3])} 分隔"
    else:
        return "/".join(letters + nums)

def check_answer(user_answer, correct_answer, is_multiple):
    if is_multiple:
        return user_answer == correct_answer
    else:
        return user_answer == correct_answer

def practice_sequential(conn):
    clear_screen()
    print("\n=== 顺序练习模式 ===\n")

    questions = get_all_questions(conn)
    if not questions:
        print("No questions available.")
        input("按回车返回主菜单...")
        return

    cursor = conn.cursor()
    cursor.execute("SELECT question_id FROM user_stats WHERE total_attempts = 0 ORDER BY question_id LIMIT 1")
    first_unanswered = cursor.fetchone()

    start_index = 0
    if first_unanswered:
        for i, q in enumerate(questions):
            if q["id"] == first_unanswered["question_id"]:
                start_index = i
                break

    current_index = start_index

    while current_index < len(questions):
        question = questions[current_index]
        shuffled_options, new_correct, display_map, display_to_orig, is_mc = shuffle_options(question)

        if not shuffled_options:
            print(f"题目 {question['id']} 格式不完整，跳过。")
            current_index += 1
            continue

        num_options = len(shuffled_options)
        input_hint = build_input_hint(num_options, is_mc)

        display_question(question, shuffled_options)

        user_input = input(f"请输入答案 ({input_hint}，输入 Q 返回菜单): ")

        answer, is_parsed = parse_user_input(user_input, num_options)

        if answer == "Q":
            break

        if answer is None:
            print("输入无效，请重新输入。")
            continue

        correct = check_answer(answer, new_correct, is_mc)
        update_stats(conn, question["id"], correct)

        if correct:
            print("\n✓ 正确！")
        else:
            print(f"\n✗ 错误！正确答案是 {new_correct}")
            if is_mc:
                print(f"  （需选对所有正确选项）")

        stats = get_user_stats(conn, question["id"])
        print(f"  该题总作答次数: {stats['total_attempts']}, 错题次数: {stats['wrong_attempts']}")

        current_index += 1

        if current_index < len(questions):
            cont = input("\n按回车继续下一题，输入 Q 返回菜单: ")
            if cont.strip().upper() == "Q":
                break
        else:
            print("\n所有题目已完成！")

    input("\n按回车返回主菜单...")

def practice_random(conn):
    clear_screen()
    print("\n=== 随机跳题模式 ===\n")

    questions = get_all_questions(conn)
    if not questions:
        print("No questions available.")
        input("按回车返回主菜单...")
        return

    while True:
        question = random.choice(questions)
        shuffled_options, new_correct, display_map, display_to_orig, is_mc = shuffle_options(question)

        if not shuffled_options:
            continue

        num_options = len(shuffled_options)
        input_hint = build_input_hint(num_options, is_mc)

        display_question(question, shuffled_options)

        user_input = input(f"请输入答案 ({input_hint}，输入 Q 返回菜单): ")

        answer, is_parsed = parse_user_input(user_input, num_options)

        if answer == "Q":
            break

        if answer is None:
            print("输入无效，请重新输入。")
            continue

        correct = check_answer(answer, new_correct, is_mc)
        update_stats(conn, question["id"], correct)

        if correct:
            print("\n✓ 正确！")
        else:
            print(f"\n✗ 错误！正确答案是 {new_correct}")
            if is_mc:
                print(f"  （需选对所有正确选项）")

        stats = get_user_stats(conn, question["id"])
        print(f"  该题总作答次数: {stats['total_attempts']}, 错题次数: {stats['wrong_attempts']}")

        cont = input("\n按回车继续，输入 Q 返回菜单: ")
        if cont.strip().upper() == "Q":
            break

    input("\n按回车返回主菜单...")

def practice_wrong(conn):
    clear_screen()
    print("\n=== 错题练习模式 ===\n")

    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.* FROM questions q
        JOIN user_stats s ON q.id = s.question_id
        WHERE s.wrong_attempts > 0
        ORDER BY s.wrong_attempts DESC
    """)
    wrong_questions = [load_question(row) for row in cursor.fetchall()]

    if not wrong_questions:
        print("暂无错题记录！继续保持！")
        input("\n按回车返回主菜单...")
        return

    print(f"当前共有 {len(wrong_questions)} 道错题。\n")

    wrong_list = list(wrong_questions)

    while wrong_list:
        question = wrong_list.pop(0)

        shuffled_options, new_correct, display_map, display_to_orig, is_mc = shuffle_options(question)

        if not shuffled_options:
            continue

        num_options = len(shuffled_options)
        input_hint = build_input_hint(num_options, is_mc)

        stats = get_user_stats(conn, question["id"])
        print(f"\n[错题次数: {stats['wrong_attempts']}]")

        display_question(question, shuffled_options)

        user_input = input(f"请输入答案 ({input_hint}，输入 Q 返回菜单): ")

        answer, is_parsed = parse_user_input(user_input, num_options)

        if answer == "Q":
            break

        if answer is None:
            print("输入无效，请重新输入。")
            wrong_list.append(question)
            continue

        correct = check_answer(answer, new_correct, is_mc)
        update_stats(conn, question["id"], correct)

        if correct:
            print("\n✓ 正确！错题次数已减少。")
            cursor.execute("""
                UPDATE user_stats SET wrong_attempts = MAX(0, wrong_attempts - 1)
                WHERE question_id = ?
            """, (question["id"],))
            conn.commit()
            new_stats = get_user_stats(conn, question["id"])
            if new_stats["wrong_attempts"] <= 0:
                print("  该题已从错题本移除！")
        else:
            print(f"\n✗ 错误！正确答案是 {new_correct}")
            if is_mc:
                print(f"  （需选对所有正确选项）")
            wrong_list.append(question)

        stats = get_user_stats(conn, question["id"])
        print(f"  该题当前错题次数: {stats['wrong_attempts']}")

        if wrong_list:
            cont = input("\n按回车继续，输入 Q 返回菜单: ")
            if cont.strip().upper() == "Q":
                break
        else:
            print("\n恭喜！所有错题已清零！")

    input("\n按回车返回主菜单...")

def show_statistics(conn):
    clear_screen()
    print("\n=== 统计信息 ===\n")

    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM questions")
    total_questions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM questions WHERE is_multiple_choice = 1")
    mc_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM user_stats WHERE total_attempts > 0")
    attempted_questions = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(total_attempts), SUM(wrong_attempts) FROM user_stats")
    row = cursor.fetchone()
    total_attempts = row[0] or 0
    total_wrong = row[1] or 0

    print(f"总题目数: {total_questions}")
    print(f"已作答题目数: {attempted_questions}")
    print(f"未作答题目数: {total_questions - attempted_questions}")
    print(f"总作答次数: {total_attempts}")
    print(f"总错误次数: {total_wrong}")

    if total_attempts > 0:
        overall_accuracy = (1 - total_wrong / total_attempts) * 100
        print(f"\n总体正确率: {overall_accuracy:.1f}%")
    else:
        print("\n总体正确率: 暂无数据")

    print("\n--- 每道题正确率 ---")
    cursor.execute("""
        SELECT q.id, q.text, q.is_multiple_choice, s.total_attempts, s.wrong_attempts,
               CASE WHEN s.total_attempts > 0
                    THEN ROUND((1.0 - CAST(s.wrong_attempts AS FLOAT) / s.total_attempts) * 100, 1)
                    ELSE NULL
               END as accuracy
        FROM questions q
        JOIN user_stats s ON q.id = s.question_id
        WHERE s.total_attempts > 0
        ORDER BY accuracy ASC
    """)

    rows = cursor.fetchall()
    if rows:
        print(f"{'题号':<6} {'类型':<4} {'正确率':<8} {'作答次数':<10} {'错误次数':<10} {'题干'}")
        print("-" * 90)
        for row in rows:
            acc = f"{row['accuracy']}%" if row['accuracy'] is not None else "N/A"
            type_tag = "多" if row['is_multiple_choice'] else "单"
            text_preview = row['text'][:30] + "..." if len(row['text']) > 30 else row['text']
            print(f"Q{row['id']:<5} {type_tag:<4} {acc:<8} {row['total_attempts']:<10} {row['wrong_attempts']:<10} {text_preview}")
    else:
        print("暂无作答记录。")

    print("\n--- Top 5 错题 ---")
    cursor.execute("""
        SELECT q.id, q.text, q.is_multiple_choice, s.wrong_attempts
        FROM questions q
        JOIN user_stats s ON q.id = s.question_id
        WHERE s.wrong_attempts > 0
        ORDER BY s.wrong_attempts DESC
        LIMIT 5
    """)

    wrong_rows = cursor.fetchall()
    if wrong_rows:
        for i, row in enumerate(wrong_rows, 1):
            type_tag = "[多]" if row['is_multiple_choice'] else "[单]"
            text_preview = row['text'][:40] + "..." if len(row['text']) > 40 else row['text']
            print(f"  {i}. {type_tag} Q{row['id']} (错 {row['wrong_attempts']} 次): {text_preview}")
    else:
        print("暂无错题记录。")

    input("\n按回车返回主菜单...")

def reset_wrong_records(conn):
    clear_screen()
    print("\n=== 重置错题记录 ===\n")

    confirm = input("确定要重置所有错题记录吗？(Y/N): ")
    if confirm.strip().upper() != "Y":
        print("已取消。")
        input("\n按回车返回主菜单...")
        return

    cursor = conn.cursor()
    cursor.execute("UPDATE user_stats SET wrong_attempts = 0")
    conn.commit()

    print("所有错题记录已重置！")
    input("\n按回车返回主菜单...")

def main_menu(conn):
    while True:
        clear_screen()
        total = get_question_count(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_multiple_choice = 1")
        mc_count = cursor.fetchone()[0]

        print("\n" + "=" * 40)
        print("   人工智能导论 刷题系统")
        print("=" * 40)
        print(f"   题库题目数: {total}")
        print("=" * 40)
        print("   1. 顺序练习（按题号）")
        print("   2. 随机跳题（随机选题）")
        print("   3. 只刷错题（仅显示错题）")
        print("   4. 统计信息")
        print("   5. 重置错题记录")
        print("   0. 退出")
        print("=" * 40)

        choice = input("\n请选择 (0-5): ").strip()

        if choice == "1":
            practice_sequential(conn)
        elif choice == "2":
            practice_random(conn)
        elif choice == "3":
            practice_wrong(conn)
        elif choice == "4":
            show_statistics(conn)
        elif choice == "5":
            reset_wrong_records(conn)
        elif choice == "0":
            print("\n再见！")
            break
        else:
            print("无效选择，请重新输入。")
            input("\n按回车继续...")

def main():
    conn = get_db_connection()
    try:
        main_menu(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
