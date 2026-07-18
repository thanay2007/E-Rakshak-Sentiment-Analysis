"""Dedicated Machine Learning model for detecting bot accounts based on metadata."""
import logging
from app.models.models import Post

log = logging.getLogger("sentinel.bot_classifier")

_bot_model = None

def get_bot_classifier():
    """Lazy load or train the bot classifier."""
    global _bot_model
    if _bot_model is not None:
        return _bot_model
        
    try:
        from sklearn.ensemble import RandomForestClassifier
        import numpy as np
        
        # In a real scenario, this would load a pre-trained pickle file.
        # Here we mock it by training a quick RF on dummy data representing
        # the heuristic thresholds we care about.
        log.info("Initializing RandomForest bot classifier...")
        _bot_model = RandomForestClassifier(n_estimators=10, max_depth=3, random_state=42)
        
        # Features: [account_age_days, followers, following, post_count]
        X = np.array([
            [1, 5, 2000, 150],     # Bot: new, few followers, mass following, high posts
            [500, 1500, 500, 30],  # Human: old, balanced, normal posts
            [2, 0, 50, 80],        # Bot: new, zero followers, mass posting
            [1000, 10, 10, 5]      # Human: old lurker
        ])
        y = np.array([1, 0, 1, 0]) # 1 = bot, 0 = human
        
        _bot_model.fit(X, y)
        return _bot_model
    except ImportError:
        log.warning("scikit-learn not installed. Bot classifier disabled.")
        return None

def is_likely_bot(post: Post) -> bool:
    """Predicts if an account is a bot based on metadata."""
    if post.author_account_age_days is None:
        return False
        
    model = get_bot_classifier()
    if not model:
        # Fallback to simple heuristics if sklearn isn't available
        return post.author_account_age_days < 7
        
    import numpy as np
    # Assume some defaults for missing metadata not present in the base schema
    followers = getattr(post, 'author_followers', 0) or 0
    following = getattr(post, 'author_following', followers + 100) or 100
    post_count = 50 # Mock value for this session
    
    X = np.array([[post.author_account_age_days, followers, following, post_count]])
    prediction = model.predict(X)[0]
    
    return bool(prediction == 1)
