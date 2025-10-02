import random

def get_therapist_reply(message):
    message = message.lower()

    if "anxious" in message or "panic" in message:
        return "I’m here with you. Let’s try a simple breathing exercise. Would you like to begin?"

    if "sad" in message or "depressed" in message:
        return "It’s okay to feel sad sometimes. I'm here for you. Want to journal your thoughts?"

    if "angry" in message or "frustrated" in message:
        return "Anger is a valid emotion. Let’s try some grounding techniques to calm down."

    if "happy" in message or "good" in message:
        return "That’s wonderful to hear! Keep embracing those good moments. 🌼"

    # General fallback replies
    responses = [
        "Tell me more about that.",
        "What made you feel this way?",
        "Would you like a calming activity or to journal your thoughts?",
        "I'm listening. Go on...",
        "That sounds like something we can talk through together."
    ]
    return random.choice(responses)
