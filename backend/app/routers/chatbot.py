import re
import os
import string
import dns.resolver
from fastapi import APIRouter, Request, Depends
from openai import OpenAI
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import pip_system_certs
import logging

from app.config.database import get_db
from app.services.chatbot_service import search_knowledge_base, process_query
from app.config.dns_config import get_nameserver_groups

load_dotenv()
os.environ.update({
    "OPENAI_API_KEY": os.getenv("Open_API_KEY"),
    "OPENAI_BASE_URL": "https://openai.com",

})

client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])

router = APIRouter()

logging.basicConfig(filename='chatbot_interactions.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# Helper: highlight DNS/IP/CNAME in response
def highlight_dns_response(text):
    text = re.sub(r'([a-zA-Z0-9\-_]+\.[a-zA-Z0-9\.\-_]+)', r'<span class="dns-name">\1</span>', text)
    text = re.sub(r'(\b\d{1,3}(?:\.\d{1,3}){3}\b)', r'<span class="ip-address">\1</span>', text)
    text = re.sub(r'(CNAME record\(s\) for [^:]+: )(.+)', r'\1<span class="cname">\2</span>', text)
    return text

def dns_lookup(domain, nameservers):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = nameservers
    resolver.timeout = 5
    resolver.lifetime = 5
    output = []
    ip_match = re.match(r'^\d{1,3}(?:\.\d{1,3}){3}$', domain)
    if ip_match:
        # Only do PTR lookup for IP input
        try:
            reversed_ip = '.'.join(domain.split('.')[::-1]) + '.in-addr.arpa'
            answers = resolver.resolve(reversed_ip, 'PTR')
            values = [rdata.to_text() for rdata in answers]
            output.append(f"PTR record(s) for {domain}: {', '.join(values)}")
        except Exception as e:
            output.append(f"Could not resolve PTR record for {domain}: {e}")
    else:
        # For domain, do A and CNAME
        for rtype in ['A', 'CNAME']:
            try:
                answers = resolver.resolve(domain, rtype)
                if rtype == 'A':
                    values = [rdata.address for rdata in answers]
                elif rtype == 'CNAME':
                    values = [rdata.target.to_text() for rdata in answers]
                output.append(f"{rtype} record(s) for {domain}: {', '.join(values)}")
            except Exception as e:
                output.append(f"Could not resolve {rtype} record for {domain}: {e}")
    if output:
        result = "\n".join(output)
    else:
        result = f"No DNS records found for {domain}."
    result = highlight_dns_response(result)
    return result

# Nameserver map - loaded dynamically from config
def get_nameserver_map():
    """Get nameserver map from centralized config"""
    groups = get_nameserver_groups()
    # Return first nameserver from each group for simple lookups
    return {
        key: [servers[0]] if servers else []
        for key, servers in groups.items()
    }

NAMESERVER_MAP = get_nameserver_map()

@router.get("/chatbot")
def chatbot_get(message: str = "", db: Session = Depends(get_db)):
    """
    GET endpoint for chatbot queries
    Handles DNS lookups and knowledge base queries
    """
    user_message = message.strip()
    user_message_lower = user_message.lower()
    
    # Handle greetings
    if user_message_lower in ["hi", "hello", "hey", "hai", "help"]:
        return {"response": "Hello! I can help with DNS, DHCP, and general questions. Try: 'check dns: example.com' or ask anything!"}
    
    # Check for explicit DNS lookup command
    match = re.search(r'(check dns|dns check)[:\s]+([a-zA-Z0-9\.-_]+)', user_message_lower)
    if match:
        domain = match.group(2)
        nameservers = NAMESERVER_MAP.get('root', ["8.8.8.8"])
        dns_result = dns_lookup(domain, nameservers)
        return {"response": dns_result}
    
    # Auto-detect DNS name in message and perform lookup
    domain_match = re.search(r'\b([a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})\b', user_message)
    if domain_match:
        domain = domain_match.group(1)
        nameservers = NAMESERVER_MAP.get('root', ["8.8.8.8"])
        dns_result = dns_lookup(domain, nameservers)
        return {"response": dns_result}
    
    # Query knowledge base (PostgreSQL with semantic search)
    answer = process_query(user_message, db=db)
    return {"response": answer}

@router.post("/")
async def chatbot_endpoint(request: Request, db: Session = Depends(get_db)):
    """
    POST endpoint for chatbot queries
    Handles DNS lookups and knowledge base queries
    """
    data = await request.json()
    question = data.get("question", "")
    
    user_message = question.strip()
    user_message_lower = user_message.lower()
    
    # Handle greetings
    if user_message_lower in ["hi", "hello", "hey", "hai", "help"]:
        return {"answer": "Hello! I can help with DNS, DHCP, and general questions. Try: 'check dns: example.com' or ask anything!"}
    
    # Check for explicit DNS lookup command
    match = re.search(r'(check dns|dns check)[:\s]+([a-zA-Z0-9\.-_]+)', user_message_lower)
    if match:
        domain = match.group(2)
        nameservers = NAMESERVER_MAP.get('root', ["8.8.8.8"])
        dns_result = dns_lookup(domain, nameservers)
        return {"answer": dns_result}
    
    # Auto-detect DNS name in message and perform lookup
    domain_match = re.search(r'\b([a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})\b', user_message)
    if domain_match:
        domain = domain_match.group(1)
        nameservers = NAMESERVER_MAP.get('root', ["8.8.8.8"])
        dns_result = dns_lookup(domain, nameservers)
        return {"answer": dns_result}
    
    # Query knowledge base (PostgreSQL with semantic search)
    answer = process_query(user_message, db=db)
    return {"answer": answer}


@router.post("/chatbot/feedback")
async def save_feedback(request: Request, db: Session = Depends(get_db)):
    """
    Save user feedback and auto-learn from helpful responses
    
    Request body:
    {
        "question": "What is DNS?",
        "answer": "DNS is...",
        "helpful": true,
        "category": "General"  // optional
    }
    """
    from app.services.auto_learning_service import learn_from_interaction
    
    data = await request.json()
    question = data.get("question", "")
    answer = data.get("answer", "")
    helpful = data.get("helpful", True)
    category = data.get("category", "Auto-Learned")
    
    # Auto-learn if marked as helpful
    learned = learn_from_interaction(
        question=question,
        answer=answer,
        helpful=helpful,
        category=category,
        db=db
    )
    
    return {
        "status": "success",
        "learned": learned,
        "message": "Thank you for your feedback!" if learned else "Feedback recorded"
    }


@router.get("/chatbot/stats")
async def get_learning_stats(db: Session = Depends(get_db)):
    """Get statistics on auto-learned articles"""
    from app.services.auto_learning_service import get_auto_learned_stats
    
    stats = get_auto_learned_stats(db=db)
    return stats

