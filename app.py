import os
import sys
import uuid
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from utils.resume_ranker import ResumeRanker
from config import DevelopmentConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('app.log'), logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

# Set upload folder and allowed extensions
UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
ALLOWED_EXTENSIONS = app.config['ALLOWED_EXTENSIONS']

# Create upload folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'cvs'), exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_CONTENT_LENGTH']


def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')


@app.route('/upload_files', methods=['POST'])
def upload_files():
    """Process uploaded files"""
    try:
        job_description = request.form.get('job_description', '').strip()
        upload_type = request.form.get('uploadTypeHidden', 'files')
        
        logger.info("===== FORM SUBMISSION RECEIVED =====")
        logger.info(f"Request method: {request.method}")
        logger.info(f"Form data keys: {list(request.form.keys())}")
        logger.info(f"Files data keys: {list(request.files.keys())}")
        
        if not job_description:
            logger.error("Job description missing from form data!")
            flash('Job description is required', 'error')
            return redirect(url_for('index'))
        
        saved_files = []
        file_categories = {}
        
        # Process based on upload type
        if upload_type == 'files':
            files = request.files.getlist('cvs')
            logger.info(f"Number of files from 'cvs': {len(files)}")
            
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    saved_files.append(file_path)
                    file_categories[filename] = "General"
        
        else:  # folder upload
            files = request.files.getlist('folders')
            logger.info(f"Number of files from 'folders': {len(files)}")
            
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    relative_path = file.filename
                    filename = os.path.basename(relative_path)
                    
                    path_parts = relative_path.split('/')
                    category = path_parts[0] if len(path_parts) > 1 else "General"
                    
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    saved_files.append(file_path)
                    file_categories[filename] = category
        
        if not saved_files:
            flash('No valid files uploaded', 'error')
            return redirect(url_for('index'))
        
        logger.info(f"Successfully saved {len(saved_files)} files")
        
        # Initialize the resume ranker
        ranker = ResumeRanker(job_description)
        
        # Process the uploaded CVs
        ranker.process_resume_files(saved_files, file_categories)
        
        # Get the ranked results
        results = ranker.get_ranked_results()
        
        # Convert DataFrame to list of dicts for template
        results_list = results.to_dict(orient='records') if not results.empty else []
        
        if results_list:
            logger.info(f"Available fields in results: {list(results_list[0].keys())}")
        
        # Clean up uploaded files
        for file_path in saved_files:
            try:
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Could not delete {file_path}: {str(e)}")
        
        return render_template('results.html', 
                              results=results_list, 
                              job_description=job_description)
                              
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error processing files: {str(e)}", exc_info=True)
        flash(f'Error processing files: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error"""
    flash('File size is too large. Maximum size is 16MB.', 'error')
    return redirect(url_for('index'))


@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors"""
    logger.error(f"Internal server error: {str(error)}")
    flash('An internal server error occurred. Please try again.', 'error')
    return redirect(url_for('index'))


if __name__ == '__main__':
    logger.info("Starting Resume Ranker Application...")
    
    # Download spaCy model if needed
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
            logger.info("spaCy model already installed")
        except OSError:
            logger.warning("Downloading spaCy English model...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
    except ImportError:
        logger.warning("spaCy not installed. NLP functionality may be limited.")
    
    # Download NLTK resources
    try:
        import nltk
        nltk.download('punkt', quiet=True)
        nltk.download('stopwords', quiet=True)
        nltk.download('wordnet', quiet=True)
        nltk.download('omw-1.4', quiet=True)
        logger.info("NLTK resources ready")
    except Exception as e:
        logger.warning(f"Error with NLTK resources: {str(e)}")
    
    logger.info("Application ready. Starting Flask server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
