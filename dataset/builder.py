#!/usr/bin/env python3
"""
WhatsApp Chat to LLM Fine-tuning Dataset Converter
Because apparently we're training AI on business negotiations now.
"""

import pandas as pd
import json
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import argparse


class WhatsAppChatParser:
    def __init__(self):
        # Regex pattern for WhatsApp message format: [date, time] sender: message
        self.message_pattern = r'\[(\d{2}/\d{2}/\d{2}),\s*(\d{1,2}:\d{2}:\d{2}[^\]]*)\]\s*([^:]+):\s*(.*)'
        
        # Keywords to identify conversation segments
        self.conversation_starters = [
            'hello', 'hi', 'price', 'cost', 'how much', 'need', 'want', 'looking for'
        ]
        
        # Business context patterns
        self.business_patterns = {
            'pricing': ['price', 'cost', 'charge', 'rate', 'quote'],
            'timeline': ['when', 'time', 'days', 'deliver', 'timeline', 'deadline'],
            'requirements': ['need', 'details', 'information', 'fill', 'provide'],
            'negotiation': ['discount', 'best price', 'final', 'deal', 'close'],
            'payment': ['payment', 'advance', 'amount', 'pay', 'money'],
            'service_inquiry': ['caricature', 'invitation', 'video', '3d', 'functions']
        }
        
    def clean_message(self, message: str) -> str:
        """Clean message text by removing artifacts and normalizing."""
        # Remove WhatsApp artifacts
        message = re.sub(r'â€Ž.*?omitted', '', message)  # Remove media omitted text
        message = re.sub(r'â€Ž', '', message)  # Remove invisible chars
        message = re.sub(r'ðŸ.*?ðŸ»', '', message)  # Remove emojis
        message = re.sub(r'https?://\S+', '[LINK]', message)  # Replace links
        
        # Clean up whitespace
        message = ' '.join(message.split())
        
        return message.strip()
    
    def parse_messages(self, chat_text: str) -> List[Dict]:
        """Parse WhatsApp chat export into structured messages."""
        messages = []
        lines = chat_text.split('\n')
        
        current_message = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            match = re.match(self.message_pattern, line)
            
            if match:
                # Save previous message if exists
                if current_message:
                    messages.append(current_message)
                
                date_str, time_str, sender, content = match.groups()
                current_message = {
                    'date': date_str,
                    'time': time_str,
                    'sender': sender.strip(),
                    'content': self.clean_message(content),
                    'raw_content': content
                }
            else:
                # Multi-line message continuation
                if current_message:
                    current_message['content'] += ' ' + self.clean_message(line)
                    current_message['raw_content'] += ' ' + line
        
        # Don't forget the last message
        if current_message:
            messages.append(current_message)
            
        return messages
    
    def identify_conversation_type(self, message: str) -> str:
        """Classify message type based on content."""
        message_lower = message.lower()
        
        for category, keywords in self.business_patterns.items():
            if any(keyword in message_lower for keyword in keywords):
                return category
                
        return 'general'
    
    def create_conversation_pairs(self, messages: List[Dict]) -> List[Dict]:
        """Create user-assistant conversation pairs from messages."""
        pairs = []
        
        # Identify the two main speakers (usually customer and business)
        speakers = {}
        for msg in messages:
            speaker = msg['sender']
            if speaker not in speakers:
                speakers[speaker] = 0
            speakers[speaker] += 1
        
        # The person with fewer messages is likely the customer
        sorted_speakers = sorted(speakers.items(), key=lambda x: x[1])
        if len(sorted_speakers) >= 2:
            customer = sorted_speakers[0][0]  # Fewer messages
            business = sorted_speakers[1][0]   # More messages
        else:
            # Fallback: assume first speaker is customer
            customer = list(speakers.keys())[0] if speakers else "Customer"
            business = list(speakers.keys())[1] if len(speakers) > 1 else "Business"
        
        i = 0
        while i < len(messages) - 1:
            current_msg = messages[i]
            next_msg = messages[i + 1]
            
            # Skip if same sender or empty content
            if (current_msg['sender'] == next_msg['sender'] or 
                not current_msg['content'].strip() or 
                not next_msg['content'].strip()):
                i += 1
                continue
            
            # Determine roles
            if current_msg['sender'] == customer:
                user_role, assistant_role = 'user', 'assistant'
                user_msg, assistant_msg = current_msg, next_msg
            else:
                user_role, assistant_role = 'assistant', 'user'  
                assistant_msg, user_msg = current_msg, next_msg
                # But we want user first, so flip
                user_role, assistant_role = 'user', 'assistant'
                user_msg, assistant_msg = next_msg, current_msg
            
            # Skip very short or irrelevant messages
            if (len(user_msg['content']) < 3 or 
                len(assistant_msg['content']) < 3 or
                user_msg['content'] in ['.', 'ok', 'yes', 'no']):
                i += 1
                continue
            
            conversation_pair = {
                'messages': [
                    {
                        'role': 'user',
                        'content': user_msg['content']
                    },
                    {
                        'role': 'assistant', 
                        'content': assistant_msg['content']
                    }
                ],
                'metadata': {
                    'task_type': self.identify_conversation_type(user_msg['content']),
                    'date': user_msg['date'],
                    'customer_speaker': customer,
                    'business_speaker': business,
                    'language': 'hinglish' if self.is_hinglish(user_msg['content'] + ' ' + assistant_msg['content']) else 'english'
                }
            }
            
            # Add specific metadata based on content
            self.add_context_metadata(conversation_pair, user_msg['content'], assistant_msg['content'])
            
            pairs.append(conversation_pair)
            i += 2  # Skip the next message since we used it
            
        return pairs
    
    def is_hinglish(self, text: str) -> bool:
        """Detect if text contains Hindi/Hinglish."""
        hinglish_indicators = ['hai', 'ke', 'ka', 'ki', 'se', 'me', 'ko', 'mai', 'kar', 'dijiye', 'bhi', 'sir', 'bhai']
        text_lower = text.lower()
        return any(word in text_lower for word in hinglish_indicators)
    
    def add_context_metadata(self, pair: Dict, user_msg: str, assistant_msg: str):
        """Add specific metadata based on message content."""
        combined_text = (user_msg + ' ' + assistant_msg).lower()
        
        # Check for pricing information
        if 'price' in combined_text or 'cost' in combined_text or '₹' in combined_text:
            numbers = re.findall(r'\d+', assistant_msg)
            if numbers:
                pair['metadata']['price_mentioned'] = True
                pair['metadata']['price_range'] = f"{min(map(int, numbers))}-{max(map(int, numbers))}"
        
        # Check for functions/events
        function_match = re.search(r'(\d+)\s*function', combined_text)
        if function_match:
            pair['metadata']['functions_count'] = int(function_match.group(1))
        
        # Check for delivery timeline
        days_match = re.search(r'(\d+)[-\s]*(\d*)\s*days?', combined_text)
        if days_match:
            pair['metadata']['delivery_days'] = days_match.group(0)
        
        # Check for services mentioned
        services = []
        if 'caricature' in combined_text:
            services.append('caricature')
        if '3d' in combined_text:
            services.append('3d_video')
        if 'invite' in combined_text or 'invitation' in combined_text:
            services.append('invitation')
        
        if services:
            pair['metadata']['services'] = services
    
    def to_dataframe(self, conversations: List[Dict]) -> pd.DataFrame:
        """Convert conversations to pandas DataFrame."""
        rows = []
        
        for conv in conversations:
            row = {
                'user_message': conv['messages'][0]['content'],
                'assistant_message': conv['messages'][1]['content'],
                'task_type': conv['metadata'].get('task_type', 'general'),
                'language': conv['metadata'].get('language', 'english'),
                'date': conv['metadata'].get('date', ''),
                'price_mentioned': conv['metadata'].get('price_mentioned', False),
                'functions_count': conv['metadata'].get('functions_count', None),
                'services': ','.join(conv['metadata'].get('services', [])),
                'delivery_days': conv['metadata'].get('delivery_days', ''),
            }
            rows.append(row)
        
        return pd.DataFrame(rows)
    
    def save_dataset(self, conversations: List[Dict], output_format: str = 'json', filename: str = 'chat_dataset'):
        """Save dataset in specified format."""
        if output_format.lower() == 'json':
            with open(f"{filename}.json", 'w', encoding='utf-8') as f:
                json.dump(conversations, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(conversations)} conversations to {filename}.json")
        
        elif output_format.lower() == 'jsonl':
            with open(f"{filename}.jsonl", 'w', encoding='utf-8') as f:
                for conv in conversations:
                    f.write(json.dumps(conv, ensure_ascii=False) + '\n')
            print(f"Saved {len(conversations)} conversations to {filename}.jsonl")
        
        elif output_format.lower() == 'csv':
            df = self.to_dataframe(conversations)
            df.to_csv(f"{filename}.csv", index=False, encoding='utf-8')
            print(f"Saved {len(conversations)} conversations to {filename}.csv")
        
        else:
            raise ValueError(f"Unsupported format: {output_format}")


def main():
    parser = argparse.ArgumentParser(description="Convert WhatsApp chat to LLM fine-tuning dataset")
    parser.add_argument("input_file", help="Input WhatsApp chat export file")
    parser.add_argument("-o", "--output", default="chat_dataset", help="Output filename (without extension)")
    parser.add_argument("-f", "--format", choices=['json', 'jsonl', 'csv'], default='json', 
                        help="Output format")
    parser.add_argument("--min-length", type=int, default=5, 
                        help="Minimum message length to include")
    
    args = parser.parse_args()
    
    # Initialize parser
    chat_parser = WhatsAppChatParser()
    
    # Read input file
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            chat_text = f.read()
    except FileNotFoundError:
        print(f"Error: File '{args.input_file}' not found.")
        return
    except UnicodeDecodeError:
        # Try different encodings
        for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
            try:
                with open(args.input_file, 'r', encoding=encoding) as f:
                    chat_text = f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            print("Error: Could not decode the file. Try saving it as UTF-8.")
            return
    
    print(f"Processing chat file: {args.input_file}")
    
    # Parse messages
    messages = chat_parser.parse_messages(chat_text)
    print(f"Parsed {len(messages)} messages")
    
    # Create conversation pairs
    conversations = chat_parser.create_conversation_pairs(messages)
    print(f"Created {len(conversations)} conversation pairs")
    
    # Filter by minimum length if specified
    if args.min_length > 0:
        original_count = len(conversations)
        conversations = [
            conv for conv in conversations 
            if (len(conv['messages'][0]['content']) >= args.min_length and 
                len(conv['messages'][1]['content']) >= args.min_length)
        ]
        print(f"Filtered to {len(conversations)} conversations (removed {original_count - len(conversations)})")
    
    # Save dataset
    if conversations:
        chat_parser.save_dataset(conversations, args.format, args.output)
        
        # Print some stats
        task_types = {}
        for conv in conversations:
            task_type = conv['metadata'].get('task_type', 'unknown')
            task_types[task_type] = task_types.get(task_type, 0) + 1
        
        print("\nConversation types:")
        for task_type, count in sorted(task_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  {task_type}: {count}")
    else:
        print("No valid conversations found. Check your input file format.")


if __name__ == "__main__":
    main()
