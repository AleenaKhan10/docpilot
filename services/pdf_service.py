import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from datetime import datetime
from itertools import groupby

# Define Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

def generate_pdf_report(video_obj, steps, output_path):
    """
    Generates a professional Help Center style PDF report.
    - Groups steps by Section (Title).
    - Includes section summaries, explanations, tips, notes, and URLs.
    """
    
    # 1. Setup Jinja2
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("report.html")
    
    # 2. Fix CSS Path
    css_file_path = os.path.join(TEMPLATE_DIR, "style.css")
    css_obj = CSS(filename=css_file_path)

    # 3. Professional Section Grouping
    sections = []
    current_section = None
    
    for step in steps:
        step_title = getattr(step, "title", "General Steps")
        step_desc = getattr(step, "description", "")
        step_time = getattr(step, "timestamp", "")
        step_num = getattr(step, "step_number", 0)
        step_tip = getattr(step, "tip", None)
        step_url = getattr(step, "url", None)
        step_explanation = getattr(step, "explanation", None)
        step_note = getattr(step, "note", None)
        step_section_summary = getattr(step, "section_summary", None)

        # Format Step
        step_dict = {
            "step_number": step_num,
            "timestamp": step_time,
            "action": step_desc,
            "tip": step_tip,
            "url": step_url,
            "explanation": step_explanation,
            "note": step_note,
        }

        # Check if we need a new section
        if current_section is None or current_section["heading"] != step_title:
            current_section = {
                "heading": step_title,
                "summary": step_section_summary,  # Use section_summary from the first step
                "steps": []
            }
            sections.append(current_section)
        
        current_section["steps"].append(step_dict)

    # 4. Generate document summary
    section_names = [s["heading"] for s in sections]
    if len(section_names) > 1:
        doc_summary = f"This guide walks you through {len(section_names)} key sections: {', '.join(section_names[:-1])}, and {section_names[-1]}. Follow each section in order for the best results."
    elif len(section_names) == 1:
        doc_summary = f"This guide covers {section_names[0]}. Follow the steps below in order."
    else:
        doc_summary = "Follow the steps below to complete this task."

    # 5. Prepare Context for HTML
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
    
    # 6. Render HTML
    html_content = template.render(context)
    
    # 7. Generate PDF
    print(f"🎨 Generating PDF at: {output_path}")
    HTML(string=html_content, base_url=BASE_DIR).write_pdf(
        output_path, 
        stylesheets=[css_obj]
    )
    
    return output_path

# import os
# from pathlib import Path  # <--- Required for Windows Path Handling
# from jinja2 import Environment, FileSystemLoader
# from weasyprint import HTML, CSS
# from datetime import datetime

# # Define Paths
# BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# def generate_pdf_report(video_obj, steps, output_path):
#     """
#     Generates a professional PDF report from video steps.
#     Fixes Windows Path issues for Images and CSS.
#     """
    
#     # 1. Setup Jinja2 Template Environment
#     env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
#     template = env.get_template("report.html")
    
#     # 2. Fix CSS Path (Load content directly to avoid path errors)
#     css_file_path = os.path.join(TEMPLATE_DIR, "style.css")
#     css_obj = CSS(filename=css_file_path)

#     # 3. Process Steps & Fix Image Paths
#     processed_steps = []
#     for step in steps:
#         # Absolute path banayo
#         abs_img_path = os.path.join(BASE_DIR, step.image_url)
        
#         # CRITICAL FIX FOR WINDOWS:
#         # Convert "D:\Projects\..." to "file:///D:/Projects/..."
#         # pathlib automatically handles slashes and spaces (%20)
#         image_uri = Path(abs_img_path).as_uri()
        
#         processed_steps.append({
#             "step_number": step.step_number,
#             "timestamp": step.timestamp,
#             "description": step.description,
#             "image_url": image_uri  # Now it's a valid URI and in correct format
#         })

#     # 4. Context Preparation
#     # Note: css_path HTML mein pass karne ki zaroorat nahi kyunki hum Python se inject kar rahe hain
#     context = {
#         "video": video_obj,
#         "steps": processed_steps,
#         "date": datetime.now().strftime("%B %d, %Y"),
#     }
    
#     # 5. Render HTML
#     html_content = template.render(context)
    
#     # 6. Convert to PDF
#     print(f"🎨 Generating PDF at: {output_path}")
    
#     # Base URL zaroori hai taake agar koi relative path ho tow wo resolve ho sake
#     HTML(string=html_content, base_url=BASE_DIR).write_pdf(
#         output_path, 
#         stylesheets=[css_obj] # CSS object pass kiya direct
#     )
    
#     return output_path