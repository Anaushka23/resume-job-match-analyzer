# Resume and Job Match Analyzer

I made this to check how well my own resume matches a job description before applying. You paste (or upload) a resume and paste a job description, and it gives you a score out of 100, the skills that match, the skills that are missing, and some suggestions to improve the resume. Every analysis gets saved, so you can edit your resume, run it again, and see if the score actually went up.

Built with Python, Streamlit and the Google Gemini API. I used an AI coding assistant to help write the code, but I went through each file and phase one by one so I could understand and explain how it works.

## What it does

- Takes a resume as a PDF upload or pasted text, plus a job description
- Gives a match score out of 100, split into 4 categories (see below)
- Lists matched skills and missing skills (missing ones are marked high / medium / low importance)
- Gives suggestions for improving the resume, each linked to a section (skills, projects, etc.)
- Saves every analysis so you can look at them later on the History page
- Compare page: pick two analyses and see how the scores changed (useful for before/after editing)
- Download an analysis as a Markdown file
- Shows a proper error message for things like empty PDFs, scanned PDFs, or API failures instead of crashing

## How the scoring works

The model is given a rubric before it reads the resume, so the marks are not random.

| Category | Max points |
|---|---|
| Skills match | 40 |
| Experience relevance | 25 |
| ATS keywords | 20 |
| Education and projects | 15 |

LLMs can give a different score each time for the same input, so I tried to reduce that:

- `temperature=0` so the model is as predictable as possible
- the output is forced into a fixed JSON format and checked with Pydantic
- the code checks that the four category scores add up to the overall score, and fixes the total if the model's maths is wrong

This makes the scores a lot more stable, but not perfect. Running the same input a few times can still give slightly different results.

## Tech used

| Tool | Used for |
|---|---|
| Python 3.11+ | main language |
| Streamlit | the web interface |
| Google Gemini API (`google-genai`) | the AI part |
| Pydantic | validating the AI's output |
| pdfplumber | reading text from PDFs |
| SQLite | default storage |
| MongoDB (pymongo) | optional storage, same interface as SQLite |
| python-dotenv | reading the API key from `.env` |
| pytest | tests |

No LangChain or similar frameworks. I called the API directly because I wanted to understand what is actually happening.

## Project structure

```
resume-analyzer/
├── app.py                 # Streamlit UI only
├── config.py              # settings, logging, loads .env
├── requirements.txt
├── .env.example           # template for the .env file
├── models/
│   └── schemas.py         # Pydantic models for the analysis result
├── services/
│   ├── prompts.py         # prompt text and scoring rubric
│   ├── pdf_reader.py      # extracts text from PDFs
│   └── analyzer.py        # calls Gemini, retries, validates
├── storage/
│   ├── base.py            # abstract storage interface
│   ├── sqlite_store.py    # SQLite version
│   └── mongo_store.py     # MongoDB version
└── tests/                 # pytest tests (Gemini is mocked)
```

The idea was to keep each file to one job. `app.py` only handles the screen, `analyzer.py` handles the AI, and the storage files handle saving. Because the app only talks to the storage interface, I could add the MongoDB version without changing the UI.

## How to run it

1. Install Python 3.11 or higher.
2. Get a free Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
3. Download the project and install the libraries:
   ```
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and put your key in it:
   ```
   GEMINI_API_KEY=your_key_here
   ```
   Never upload your `.env` to GitHub. It is already in `.gitignore`.
5. Start the app:
   ```
   python -m streamlit run app.py
   ```
6. Open `http://localhost:8501` in your browser.

To run the tests:
```
python -m pytest tests/ -v
```
The last time I ran them, all 29 passed. They don't use the real API.

## Choosing the database

SQLite is the default and needs nothing extra. For MongoDB, start MongoDB on your laptop (it uses `mongodb://localhost:27017` and a database called `resumeAnalyzerDB`) and switch the storage setting in `config.py`.

<!-- TODO: replace the line above with the exact setting name from config.py -->

## What I learned

- How to call an LLM from Python and get structured JSON back instead of free text
- Why validating the AI's output matters (it sometimes returns wrong or badly formatted data)
- Keeping the UI, AI logic and storage in separate files so each is easy to change and test
- Handling things that can go wrong: empty PDFs, bad JSON, rate limits, API errors
- Writing tests with the API mocked, so they run without internet or a key

## Limitations

- The score comes from an AI model, so treat it as guidance, not an exact number
- Scanned or image-only PDFs don't work, since there is no text to read (the app tells you this)
- No login. Everyone who uses the same copy of the app shares the same history
- The frontend is basic. I focused on getting the logic right first
- Only tested with English resumes

## Things I want to add

- Keyword highlighting directly on the resume text
- OCR for scanned PDFs
- Deploying it so it has a live link
- A nicer interface
