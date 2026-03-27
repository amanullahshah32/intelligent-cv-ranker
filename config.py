# Configuration file for Resume Ranker Application
import os

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-for-flash-messages'
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload size
    ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}
    
    # OCR Configuration - Updated for your system
    TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    POPPLER_PATH = r'C:\Users\amanu\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin'
    
    # Resume Ranker Configuration
    SCORING_WEIGHTS = {
        'education': 0.15,
        'experience': 0.20,
        'skills': 0.15,
        'certifications': 0.10,
        'projects': 0.10,
        'jd_similarity': 0.30
    }
    
    SKILL_THRESHOLD = 85
    MAX_WORKERS = 4
    HR_FEEDBACK_TOP_N = 50
    FEEDBACK_MIN_RANK = 5
    FEEDBACK_MAX_RANK = 20
    BENCHMARK_SAMPLE = 0.2


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False


class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    UPLOAD_FOLDER = 'test_uploads'


# Configuration dictionary
config_dict = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config(env='development'):
    """Get configuration object for the specified environment"""
    return config_dict.get(env, DevelopmentConfig)
