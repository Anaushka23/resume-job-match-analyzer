"""
services/prompts.py - All prompt text lives here, away from business logic.

WHY ISOLATE PROMPTS?
Prompt engineering is iterative. Keeping prompts in a dedicated file means
you can tune the wording, rubric, or examples without touching any Python
logic. Think of it like keeping SQL queries in .sql files instead of
embedding them deep in application code.
"""


# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------
# This is sent to Gemini as the "system" role — it defines the AI's persona
# and the non-negotiable rules it must always follow in every request.
SYSTEM_PROMPT = """You are an expert technical recruiter and resume coach with 15 years 
of experience in software engineering hiring.

Your job is to analyze how well a candidate's resume matches a given job description.
You must follow the scoring rubric EXACTLY as provided. Do not deviate from the 
category weights or the criteria described.

CRITICAL RULES:
1. overall_score MUST be the EXACT sum of all four category_scores values, rounded 
   to the nearest whole number.
2. Never invent skills or experiences not present in the resume.
3. Be specific and actionable — avoid vague feedback like "improve your resume".
4. Output valid JSON only, conforming exactly to the schema provided.
"""


# ---------------------------------------------------------------------------
# SCORING RUBRIC (embedded in each analysis prompt)
# ---------------------------------------------------------------------------
# WHY A RUBRIC? Without explicit grading criteria, the model gives different
# scores for identical resumes on different runs. A detailed rubric forces
# consistent, reproducible scoring — similar to how professors use marking 
# schemes to ensure fair grading.
RUBRIC = """
=== SCORING RUBRIC (follow this exactly) ===

[1] skills_match — Maximum 40 points
    • 36-40 pts: ALL required skills present; majority of preferred skills present.
    • 25-35 pts: Most required skills present; some preferred skills missing.
    • 15-24 pts: About half of required skills present; many gaps.
    • 6-14 pts:  Only a few required skills present.
    • 0-5 pts:   Fundamental skill mismatch; very few or no required skills present.

[2] experience_relevance — Maximum 25 points
    • 22-25 pts: Direct, quantified experience in the exact domain/industry; 
                  clear leadership or ownership shown.
    • 15-21 pts: Mostly relevant experience; some transferable work in similar domain.
    • 8-14 pts:  Partially relevant; gaps in seniority, domain, or years of experience.
    • 3-7 pts:   Limited relevant experience; mostly unrelated roles.
    • 0-2 pts:   No meaningful relevant work experience.

[3] keywords_ats — Maximum 20 points
    ATS = Applicant Tracking System. Recruiters use software that scans for 
    exact keywords before a human ever sees the resume.
    • 17-20 pts: High keyword density; critical job-description phrases appear 
                  verbatim in resume.
    • 11-16 pts: Good keyword coverage; a few important terms paraphrased or missing.
    • 6-10 pts:  Moderate coverage; several ATS-critical terms absent.
    • 2-5 pts:   Low coverage; mostly mismatched terminology.
    • 0-1 pts:   Almost no keyword overlap.

[4] education_and_projects — Maximum 15 points
    • 13-15 pts: Degree directly matches role; certifications and projects are 
                  highly relevant and technically impressive.
    • 9-12 pts:  Degree partially matches; some relevant projects or certifications.
    • 5-8 pts:   General degree; a few related projects.
    • 2-4 pts:   Unrelated degree; minimal or generic projects.
    • 0-1 pts:   No relevant education or project experience.

REMINDER: overall_score = sum of all four category scores (rounded to nearest int).
"""


# ---------------------------------------------------------------------------
# ANALYSIS PROMPT TEMPLATE
# ---------------------------------------------------------------------------
# This is the main user-role message. The placeholders {resume_text} and 
# {job_description} are filled in by analyzer.py at runtime using Python's
# str.format() method.
ANALYSIS_PROMPT_TEMPLATE = """
Analyze how well the following resume matches the job description provided.

Apply the scoring rubric above to assign scores to each category.
Then generate the full structured analysis.

=== RESUME ===
{resume_text}

=== JOB DESCRIPTION ===
{job_description}

=== OUTPUT INSTRUCTIONS ===
Return a single JSON object with these fields:
- overall_score: integer (0-100). MUST equal sum of all four category scores.
- category_scores: object with keys:
    skills_match (max 40), experience_relevance (max 25), 
    keywords_ats (max 20), education_and_projects (max 15)
- matched_skills: list of strings (skills present in both resume and job description)
- missing_skills: list of objects, each with "skill" (string) and 
  "importance" ("high"/"medium"/"low")
- strengths: list of 3-5 short strings describing where the candidate excels
- suggestions: list of 5-8 objects, each with:
    "section" (which resume section to fix, e.g., "Work Experience", "Skills", 
    "Projects", "Summary", "Education")
    "suggestion" (a specific, actionable improvement — be precise, not generic)
- one_line_summary: string (1 sentence executive summary of overall fit)
"""


def build_analysis_prompt(resume_text: str, job_description: str) -> str:
    """
    Assembles the final prompt by injecting the resume and job description
    into the template, along with the scoring rubric.

    Args:
        resume_text: Extracted plain text from the candidate's resume.
        job_description: The job listing text pasted by the user.

    Returns:
        A complete, ready-to-send prompt string for the Gemini API.
    """
    # We prepend the rubric so the model has grading criteria in front of it
    # before it even reads the resume. This improves adherence.
    prompt_body = ANALYSIS_PROMPT_TEMPLATE.format(
        resume_text=resume_text.strip(),
        job_description=job_description.strip()
    )
    return RUBRIC + "\n" + prompt_body
