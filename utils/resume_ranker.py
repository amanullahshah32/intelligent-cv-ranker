from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict
import os
import re
import logging
import random
import nltk
import pandas as pd
import pdfplumber
import docx
import spacy
from fuzzywuzzy import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
import pytesseract
from pdf2image import convert_from_path
import cv2
import numpy as np
from PIL import Image

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('resume_ranker.log'), logging.StreamHandler()]
)

# Simple fallback lemmatizer class
class LegacyLemmatizer:
    """Fallback lemmatizer when NLTK's doesn't work"""
    def lemmatize(self, word):
        """Simple lemmatization rules"""
        if word.endswith('ing'):
            return word[:-3]
        if word.endswith('ed'):
            return word[:-2]
        if word.endswith('s') and not word.endswith('ss'):
            return word[:-1]
        return word

class ResumeRanker:
    """Intelligent resume ranking system for web application"""
    
    def __init__(self, job_description: str = None):
        self.job_description = job_description
        self.all_resumes = []
        
        # Initialize NLTK with error handling
        self._init_nltk_resources()
        
        try:
            # Load spaCy model
            self.nlp = spacy.load("en_core_web_sm")
        except Exception as e:
            logging.error(f"Error initializing spaCy: {str(e)}")
            self.nlp = None
        
        # Initialize OCR capabilities
        self._init_ocr_capabilities()
        
        # Initialize feedback templates
        self._init_feedback_templates()
        
        # Configuration
        self.config = {
            'scoring_weights': {
                'education': 0.15,
                'experience': 0.20,
                'skills': 0.15,
                'certifications': 0.10,
                'projects': 0.10,
                'jd_similarity': 0.30
            },
            'skill_threshold': 85,
            'max_workers': 4,
            'hr_feedback_top_n': 50,
            'feedback_min_rank': 5,
            'feedback_max_rank': 20,
            'benchmark_sample': 0.2
        }
        
        # Enhanced skill matrix
        self.skill_matrix = {
            'programming': ['python', 'java', 'c++', 'javascript', 'sql', 'r', 
                           'html5', 'css3', 'react', 'node.js', 'angular', 'vue.js'],
            'data_science': ['machine learning', 'deep learning', 'data analysis', 
                            'pandas', 'numpy', 'tensorflow', 'pytorch', 'nlp'],
            'cloud': ['aws', 'azure', 'gcp', 'docker', 'kubernetes', 'terraform'],
            'databases': ['mysql', 'postgresql', 'mongodb', 'oracle', 'redis'],
            'devops': ['ci/cd', 'jenkins', 'ansible', 'git', 'linux', 'bash'],
            'design': ['ui/ux', 'figma', 'adobe xd', 'photoshop', 'sketch']
        }
        
        # Education terms
        self.education_terms = {
            'bachelor': {
                'score': 3,
                'keywords': ['bachelor', 'bs', 'bsc', 'ba', 'b.tech', 'undergraduate'],
                'degrees': ['bsc', 'ba', 'bcom', 'beng']
            },
            'master': {
                'score': 4,
                'keywords': ['master', 'ms', 'm.sc', 'mba', 'postgraduate'],
                'degrees': ['msc', 'ma', 'mba', 'meng']
            },
            'phd': {
                'score': 5,
                'keywords': ['phd', 'doctorate', 'doctoral'],
                'degrees': ['phd']
            },
            'diploma': {
                'score': 2,
                'keywords': ['diploma', 'associate', 'certificate'],
                'degrees': ['diploma']
            }
        }
        
        # Certification patterns
        self.certifications = {
            'aws': ['aws certified', 'amazon web services'],
            'google': ['google cloud certified'],
            'microsoft': ['microsoft certified'],
            'pmp': ['project management professional'],
            'scrum': ['scrum master', 'agile certified']
        }

    def _init_nltk_resources(self):
        """Initialize NLTK resources with error handling"""
        try:
            nltk.download('punkt', quiet=True)
            nltk.download('stopwords', quiet=True)
            nltk.download('wordnet', quiet=True)
            nltk.download('omw-1.4', quiet=True)
            
            self.lemmatizer = WordNetLemmatizer()
            test_word = self.lemmatizer.lemmatize("testing")
            
            self.stop_words = set(stopwords.words('english'))
            self.stop_words.update({
                'resume', 'cv', 'references', 'available upon request', 'page'
            })
            
            logging.info("NLTK resources initialized successfully")
        except Exception as e:
            logging.error(f"NLTK initialization error: {str(e)}")
            self.lemmatizer = LegacyLemmatizer()
            self.stop_words = {
                'a', 'an', 'the', 'and', 'or', 'but', 'if', 'because', 'as', 
                'resume', 'cv', 'references', 'available upon request', 'page'
            }
            logging.warning("Using fallback lemmatizer and stopwords")

    def process_resume_files(self, file_paths, file_categories=None):
        """Process a list of resume files and rank them"""
        self.all_resumes = []
        
        if file_categories is None:
            file_categories = {}
        
        logging.info(f"Processing {len(file_paths)} resume files")
        
        for file_path in file_paths:
            try:
                file_name = os.path.basename(file_path)
                category = file_categories.get(file_name, "General")
                
                file_info = {
                    'path': file_path,
                    'category': category
                }
                
                result = self._process_single_resume(file_info)
                if result:
                    self.all_resumes.append(result)
                    logging.info(f"Successfully processed {file_name}")
                else:
                    logging.warning(f"No results generated for {file_name}")
                    
            except Exception as e:
                logging.error(f"Error processing {file_path}: {str(e)}")
                continue
        
        if not self.all_resumes:
            raise ValueError("No resumes could be processed successfully")
        
    def _init_ocr_capabilities(self):
        """Initialize OCR capabilities"""
        try:
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            pytesseract.get_tesseract_version()
            self.tesseract_available = True
            logging.info("Tesseract OCR initialized successfully")
        except Exception as e:
            self.tesseract_available = False
            logging.warning(f"Tesseract OCR not available: {str(e)}")
        
        self.ocr_config = {
            'use_tesseract': self.tesseract_available,
            'timeout': 120,
            'poppler_path': r'C:\Program Files\poppler\poppler-24.08.0\Library\bin'
        }

    def _init_feedback_templates(self):
        """Initialize natural language feedback templates"""
        self.feedback_templates = {
            'hr_openers': [
                "This candidate stands out because...",
                "Our analysis reveals...",
                "Key strengths include...",
                "Top ranking justified by...",
                "This profile is particularly strong in..."
            ],
            'strength_connectors': {
                'skills': [
                    "demonstrated expertise in", 
                    "proven capability with",
                    "extensive experience using"
                ],
                'education': [
                    "advanced training in",
                    "formal education focused on",
                    "degree specialization aligning with"
                ],
                'experience': [
                    "proven track record of",
                    "extensive experience in",
                    "demonstrated success with"
                ]
            },
            'jobseeker_openers': [
                "Here are some targeted suggestions to strengthen your application:",
                "To improve your candidacy for similar roles, consider:",
                "Your profile could be enhanced by addressing these areas:"
            ],
            'improvement_suggestions': [
                "Consider developing skills in {missing_skills}",
                "Highlight more quantitative achievements in past roles",
                "Obtain certification in {suggested_certification}"
            ]
        }

    def _process_single_resume(self, file_info):
        """Process individual resume"""
        try:
            raw_text = self._extract_text(file_info['path'])
            if not raw_text.strip():
                logging.warning(f"No text from {file_info['path']}")
                return None
                
            preprocessed = self.preprocess_text(raw_text)
            education_details = self._extract_education_details(preprocessed)
            experience_details = self._extract_experience(raw_text)
            contact_email = self._extract_contact_email(raw_text)
            
            return {
                'file_name': os.path.basename(file_info['path']),
                'cv_category': file_info['category'],
                'contact_email': contact_email,
                'education': education_details['highest_degree'],
                'education_score': education_details['score'],
                'experience_score': experience_details['score'],
                'experience_years': experience_details['total_years'],
                'detected_skills': self._extract_skills(preprocessed),
                'certifications': self._detect_certifications(raw_text),
                'projects': self._project_count(raw_text),
                'jd_similarity': self._calculate_jd_similarity(preprocessed),
                'skill_score': self._skill_score(preprocessed),
                'total_score': 0,
                'hr_feedback': '',
                'job_seeker_feedback': ''
            }
        except Exception as e:
            logging.error(f"Error processing {file_info['path']}: {str(e)}")
            return None

    def _extract_text(self, file_path: str) -> str:
        """Extract text from documents"""
        try:
            if file_path.lower().endswith('.pdf'):
                if self._is_scanned_pdf(file_path):
                    logging.info(f"Scanned PDF detected: {file_path}")
                    return self._extract_text_with_ocr(file_path)
                else:
                    with pdfplumber.open(file_path) as pdf:
                        text = "\n".join([page.extract_text(x_tolerance=1, y_tolerance=1) 
                                      for page in pdf.pages if page.extract_text()])
                        if text.strip():
                            return text
                        else:
                            return self._extract_text_with_ocr(file_path)
            elif file_path.lower().endswith('.docx'):
                doc = docx.Document(file_path)
                return "\n".join([para.text for para in doc.paragraphs])
            elif file_path.lower().endswith('.txt'):
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            return ""
        except Exception as e:
            logging.error(f"Failed to process {file_path}: {str(e)}")
            return ""

    def _is_scanned_pdf(self, file_path: str) -> bool:
        """Detect if PDF is scanned"""
        try:
            with pdfplumber.open(file_path) as pdf:
                text_content = ''
                image_count = 0
                
                sample_pages = min(3, len(pdf.pages))
                for i in range(sample_pages):
                    page = pdf.pages[i]
                    text = page.extract_text(x_tolerance=1, y_tolerance=1)
                    text_content += text or ''
                    
                    if page.images and len(page.images) > 0:
                        image_count += 1

                if len(text_content) < 500:
                    if image_count > 0:
                        return True
                    return len(text_content) < 100
                return False
                
        except Exception as e:
            logging.error(f"PDF analysis error: {str(e)}")
            return True

    def _extract_text_with_ocr(self, file_path: str) -> str:
        """Extract text using OCR"""
        logging.info(f"Processing with OCR: {file_path}")
        
        try:
            poppler_path = self.ocr_config['poppler_path']
            images = convert_from_path(
                file_path,
                poppler_path=poppler_path,
                thread_count=2,
                dpi=200
            )
            
            extracted_text = []
            for i, image in enumerate(images):
                img_np = np.array(image)
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
                pil_img = Image.fromarray(binary)
                
                text = pytesseract.image_to_string(
                    pil_img, 
                    lang='eng',
                    config='--psm 1 --oem 3'
                )
                extracted_text.append(text)
                logging.info(f"OCR completed for page {i+1}")
            
            return "\n".join(extracted_text)
            
        except Exception as e:
            logging.error(f"OCR failed: {str(e)}")
            return self._fallback_text_extraction(file_path)

    def _fallback_text_extraction(self, file_path: str) -> str:
        """Fallback extraction"""
        logging.info(f"Using fallback extraction for {file_path}")
        
        try:
            with pdfplumber.open(file_path) as pdf:
                text = "\n".join([p.extract_text() or "" for p in pdf.pages])
                if len(text) > 100:
                    return text
            
            return f"[EXTRACTION FAILED: {os.path.basename(file_path)}]"
            
        except Exception as e:
            logging.error(f"All extraction methods failed: {str(e)}")
            return f"[EXTRACTION FAILED: {os.path.basename(file_path)}]"

    def preprocess_text(self, text: str) -> str:
        """Preprocess text"""
        exp_numbers = re.findall(r'\d+\+?\s*(?:years?|yrs?)', text.lower())
        
        text = re.sub(r'[^\w\s+]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip().lower()
        
        tokens = nltk.word_tokenize(text)
        lemmatized = [self.lemmatizer.lemmatize(token) for token in tokens 
                      if token not in self.stop_words and len(token) > 2]
        
        return ' '.join(lemmatized + exp_numbers)

    def _extract_contact_email(self, text: str) -> str:
        """Extract email"""
        email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
        matches = re.findall(email_pattern, text)
        return matches[0] if matches else ''

    def _extract_education_details(self, text: str) -> dict:
        """Extract education"""
        education = {
            'highest_degree': 'None',
            'degrees': [],
            'score': 0
        }
        
        if self.nlp:
            doc = self.nlp(text[:10000])
            for chunk in doc.noun_chunks:
                chunk_text = chunk.text.lower()
                for degree, config in self.education_terms.items():
                    if any(fuzz.partial_ratio(kw, chunk_text) > 85 for kw in config['keywords']):
                        education['degrees'].append(degree)
                        if config['score'] > education['score']:
                            education.update({
                                'highest_degree': degree,
                                'score': config['score']
                            })
        else:
            for degree, config in self.education_terms.items():
                for keyword in config['keywords']:
                    if keyword in text.lower():
                        education['degrees'].append(degree)
                        if config['score'] > education['score']:
                            education.update({
                                'highest_degree': degree,
                                'score': config['score']
                            })
        
        return education

    def _extract_experience(self, text: str) -> dict:
        """Extract experience"""
        experience = {
            'total_years': 0,
            'score': 0
        }
        
        year_patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience',
            r'experience(?:\s+of)?\s+(\d+)\+?\s*(?:years?|yrs?)',
            r'(\d+)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+work'
        ]
        
        for pattern in year_patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                years = max(int(y) for y in matches)
                experience['total_years'] = max(experience['total_years'], years)
        
        experience['score'] = min(experience['total_years'], 10)
        
        return experience

    def _extract_skills(self, text: str) -> list:
        """Extract skills"""
        detected_skills = []
        flat_skills = [skill for category in self.skill_matrix.values() for skill in category]
        
        for skill in flat_skills:
            if skill.lower() in text.lower() or process.extractOne(
                skill, text.split(), 
                scorer=fuzz.token_set_ratio)[1] > self.config['skill_threshold']:
                detected_skills.append(skill)
        
        return list(set(detected_skills))

    def _skill_score(self, text: str) -> int:
        """Calculate skill score"""
        detected_skills = self._extract_skills(text)
        return min(len(detected_skills), 20)

    def _detect_certifications(self, text: str) -> list:
        """Detect certifications"""
        certs = set()
        text_lower = text.lower()
        for cert, keywords in self.certifications.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                    certs.add(cert)
                    break
        return list(certs)

    def _project_count(self, text: str) -> int:
        """Count projects"""
        project_keywords = r'\bproject\b|\bportfolio\b|\bwork\s+experience\b|\bselected\s+works?\b'
        sections = re.split(project_keywords, text, flags=re.IGNORECASE)
        return min(len(sections) - 1, 10)

    def _calculate_jd_similarity(self, text: str) -> float:
        """Calculate JD similarity"""
        if not self.job_description:
            return 0.0
            
        vectorizer = TfidfVectorizer(max_features=5000)
        jd_clean = self.preprocess_text(self.job_description)
        
        try:
            tfidf_matrix = vectorizer.fit_transform([jd_clean, text])
            cosine_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return cosine_sim
        except Exception as e:
            logging.error(f"Error calculating similarity: {str(e)}")
            return 0.0

    def _calculate_scores(self) -> None:
        """Calculate final scores"""
        for resume in self.all_resumes:
            scores = {
                'education': resume['education_score'],
                'experience': resume['experience_score'],
                'skills': resume['skill_score'],
                'certifications': len(resume['certifications']) * 2,
                'projects': resume['projects'],
                'jd_similarity': resume['jd_similarity'] * 10
            }
            
            weights = self.config['scoring_weights']
            resume['total_score'] = sum(scores[cat] * weights[cat] for cat in weights)

    def _generate_hr_feedback(self, candidate) -> str:
        """Generate HR feedback"""
        top_skills = candidate['detected_skills'][:3] if 'detected_skills' in candidate else []
        skills_text = ", ".join(top_skills) if top_skills else "relevant skills"
        
        opener = random.choice(self.feedback_templates['hr_openers'])
        skill_connector = random.choice(self.feedback_templates['strength_connectors']['skills'])
        
        feedback = f"{opener} {skill_connector} {skills_text}."
        
        if candidate['experience_years'] > 0:
            exp_connector = random.choice(self.feedback_templates['strength_connectors']['experience'])
            feedback += f" {exp_connector} {candidate['experience_years']} years of relevant work."
        
        if candidate['education'] != 'None':
            edu_connector = random.choice(self.feedback_templates['strength_connectors']['education'])
            feedback += f" {edu_connector} {candidate['education']} level education."
        
        return feedback

    def _identify_improvement_areas(self, candidate) -> str:
        """Generate improvement suggestions"""
        opener = random.choice(self.feedback_templates['jobseeker_openers'])
        
        suggestions = []
        
        if len(candidate['detected_skills']) < 5:
            flat_skills = [skill for category in self.skill_matrix.values() for skill in category]
            missing_skills = [s for s in flat_skills if s not in candidate['detected_skills']][:3]
            if missing_skills:
                suggestion = random.choice(self.feedback_templates['improvement_suggestions'])
                suggestion = suggestion.replace('{missing_skills}', ', '.join(missing_skills))
                suggestions.append(suggestion)
        
        if not candidate['certifications']:
            suggestion = random.choice(self.feedback_templates['improvement_suggestions'])
            cert_options = list(self.certifications.keys())
            suggested = random.choice(cert_options)
            suggestion = suggestion.replace('{suggested_certification}', suggested)
            suggestions.append(suggestion)
        
        if not suggestions:
            suggestions.append("Highlight more quantitative achievements in past roles")
        
        return f"{opener} {' '.join(suggestions)}."

    def generate_feedback(self, df) -> pd.DataFrame:
        """Generate feedback"""
        if df.empty:
            return df
        
        df['hr_feedback'] = df.apply(
            lambda row: self._generate_hr_feedback(row) 
            if row['rank'] <= self.config['hr_feedback_top_n'] else '', 
            axis=1
        )
        
        df['job_seeker_feedback'] = df.apply(
            lambda row: self._identify_improvement_areas(row)
            if self.config['feedback_min_rank'] <= row['rank'] <= self.config['feedback_max_rank'] else '',
            axis=1
        )
        
        return df

    def get_ranked_results(self):
        """Get ranked results"""
        self._calculate_scores()
        df = pd.DataFrame(self.all_resumes)
        
        if not df.empty:
            df['rank'] = df['total_score'].rank(ascending=False, method='min').astype(int)
            df = df.sort_values('rank')
            
            df = self.generate_feedback(df)
            
            cols = [
                'rank', 'file_name', 'cv_category',
                'contact_email', 'education', 'education_score', 
                'experience_score', 'experience_years',
                'detected_skills', 'certifications', 'projects',
                'jd_similarity', 'skill_score', 'total_score',
                'hr_feedback', 'job_seeker_feedback'
            ]
            available_cols = [col for col in cols if col in df.columns]
            return df[available_cols].reset_index(drop=True)
        return pd.DataFrame()
