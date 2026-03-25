# Student Attendance Tracker

A web-based student attendance management system built with Flask and powered by Claude AI. Teachers can mark attendance, view detailed reports, and get AI-generated insights and predictions for each student.

## Features

- **Mark attendance** — mark entire class as present/absent in one click with bulk actions
- **View records** — filter attendance by subject and date range
- **Student detail page** — full attendance history per student
- **Visual reports** — bar chart and doughnut chart using Chart.js
- **AI insights** — Claude AI analyses each student's attendance and gives risk assessment, pattern analysis, and teacher suggestions
- **Class report** — AI-generated class-wide analysis with recommendations
- **CSV export** — download attendance data as a spreadsheet
- **At-risk alerts** — automatic warning when >30% of students are below 75%
- **AI response caching** — API responses cached for 24 hours to reduce costs

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask |
| Database | SQLite + Flask-SQLAlchemy |
| Auth | Flask-Login + Werkzeug |
| Frontend | Bootstrap 5, Chart.js |
| AI | Anthropic Claude API |

## Project Structure

```
attendance_app/
├── app.py              # Main Flask app — all routes
├── models.py           # Database models
├── requirements.txt    # Python dependencies
├── .env                # Your secret keys (not on GitHub)
├── .env.example        # Template for .env
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── login.html
    ├── register.html
    ├── students.html
    ├── student_detail.html
    ├── subjects.html
    ├── mark_attendance.html
    ├── view_records.html
    ├── report.html
    ├── insights.html
    └── 404.html
```

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/your-username/attendance-tracker.git
cd attendance-tracker
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:
```
SECRET_KEY=your-random-secret-key
ANTHROPIC_API_KEY=sk-ant-your-api-key-here
```

Get your Anthropic API key at [console.anthropic.com](https://console.anthropic.com)

### 4. Run the app

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### 5. First time setup

1. Register a teacher account
2. Go to **Subjects** → add your subjects
3. Go to **Students** → add your students
4. Go to **Mark Attendance** → start marking!

## AI Features

The app uses the Claude API to generate:

- **Per-student insight** — risk level, absence patterns, and a teacher suggestion
- **Class report** — overall health, students needing attention, weekly recommendation

AI responses are cached for 24 hours. Click "Refresh" on any insight page to force a new analysis.

## Screenshots

> Dashboard, Reports, and AI Insights pages

## Built During

7-day project (March 14–21, 2025) as part of a 2nd year college project.

## License

MIT