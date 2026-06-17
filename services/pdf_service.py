import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

from core.logger import setup_logging

logger = setup_logging()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")


def generate_pdf_report(video_obj, steps, output_path):
    """Render the flat-step view of a video into a printable PDF.

    Groups consecutive steps that share a `title` into one section, attaches
    the first step's `section_summary` as the section intro, and includes
    explanation / tip / note / url metadata on each step.
    """
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("report.html")
    css_obj = CSS(filename=os.path.join(TEMPLATE_DIR, "style.css"))

    sections = []
    current_section = None

    for step in steps:
        step_title = getattr(step, "title", "General Steps")
        step_dict = {
            "step_number": getattr(step, "step_number", 0),
            "timestamp": getattr(step, "timestamp", ""),
            "action": getattr(step, "description", ""),
            "tip": getattr(step, "tip", None),
            "url": getattr(step, "url", None),
            "explanation": getattr(step, "explanation", None),
            "note": getattr(step, "note", None),
        }

        if current_section is None or current_section["heading"] != step_title:
            current_section = {
                "heading": step_title,
                "summary": getattr(step, "section_summary", None),
                "steps": [],
            }
            sections.append(current_section)

        current_section["steps"].append(step_dict)

    section_names = [s["heading"] for s in sections]
    if len(section_names) > 1:
        doc_summary = (
            f"This guide walks you through {len(section_names)} key sections: "
            f"{', '.join(section_names[:-1])}, and {section_names[-1]}. "
            "Follow each section in order for the best results."
        )
    elif len(section_names) == 1:
        doc_summary = (
            f"This guide covers {section_names[0]}. Follow the steps below in order."
        )
    else:
        doc_summary = "Follow the steps below to complete this task."

    total_steps = sum(len(s["steps"]) for s in sections)
    context = {
        "data": {
            "title": video_obj.title or "Documentation Guide",
            "summary": doc_summary,
            "generated_date": datetime.now().strftime("%B %d, %Y"),
            "total_sections": len(sections),
            "total_steps": total_steps,
            "sections": sections,
        },
    }

    html_content = template.render(context)
    logger.info(f"Rendering PDF: {output_path}")
    HTML(string=html_content, base_url=BASE_DIR).write_pdf(
        output_path, stylesheets=[css_obj]
    )
    return output_path
