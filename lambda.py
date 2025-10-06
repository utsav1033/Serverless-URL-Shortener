import json
import os
import string
import random
import time
import boto3
from botocore.exceptions import ClientError

# DynamoDB setup
dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ.get('TABLE_NAME', 'UrlShortener')
table = dynamodb.Table(TABLE_NAME)

# Constants
SAFE = string.ascii_letters + string.digits
CODE_LEN = 6
MAX_URL_LEN = 2048


def _make_code(length=CODE_LEN):
    """Generate random short code"""
    return ''.join(random.choices(SAFE, k=length))


def _put_unique_mapping(long_url, retries=5):
    """Store URL mapping in DynamoDB with collision handling"""
    code = _make_code()
    
    for _ in range(retries):
        try:
            table.put_item(
                Item={
                    'shortCode': code,
                    'longUrl': long_url,
                    'clicks': 0,
                    'createdAt': int(time.time()),
                    'lastAccessed': 0
                },
                ConditionExpression='attribute_not_exists(shortCode)'
            )
            return code
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                code = _make_code()
            else:
                raise
    
    raise Exception('Failed to generate unique code after retries')


def _get_long_url(short_code):
    """Retrieve long URL and increment click counter"""
    try:
        response = table.update_item(
            Key={'shortCode': short_code},
            UpdateExpression='SET clicks = clicks + :inc, lastAccessed = :time',
            ExpressionAttributeValues={
                ':inc': 1,
                ':time': int(time.time())
            },
            ReturnValues='ALL_NEW'
        )
        return response['Attributes'].get('longUrl')
    except ClientError:
        return None


def lambda_handler(event, context):
    """Main Lambda handler for API Gateway events"""
    
    print(f"Event: {json.dumps(event)}")
    
    http_method = event.get('httpMethod')
    path = event.get('path', '')
    
    # CORS headers
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
    }
    
    # Handle OPTIONS for CORS preflight
    if http_method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': ''
        }
    
    # POST /shorten - Create short URL
    if http_method == 'POST' and path == '/shorten':
        try:
            body = json.loads(event.get('body', '{}'))
            long_url = body.get('url')
            
            if not long_url:
                return {
                    'statusCode': 400,
                    'headers': headers,
                    'body': json.dumps({'error': 'URL is required'})
                }
            
            if len(long_url) > MAX_URL_LEN:
                return {
                    'statusCode': 400,
                    'headers': headers,
                    'body': json.dumps({'error': f'URL too long'})
                }
            
            short_code = _put_unique_mapping(long_url)
            
            base_url = f"https://{event['requestContext']['domainName']}/{event['requestContext']['stage']}"
            short_url = f"{base_url}/{short_code}"
            
            return {
                'statusCode': 201,
                'headers': headers,
                'body': json.dumps({
                    'shortCode': short_code,
                    'shortUrl': short_url,
                    'longUrl': long_url
                })
            }
            
        except Exception as e:
            print(f"Error: {str(e)}")
            return {
                'statusCode': 500,
                'headers': headers,
                'body': json.dumps({'error': 'Internal server error'})
            }
    
    # GET /{code} - Redirect to long URL
    elif http_method == 'GET' and len(path) > 1:
        short_code = path.lstrip('/').split('/')[0]
        
        if len(short_code) != CODE_LEN or not short_code.isalnum():
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Invalid short code'})
            }
        
        long_url = _get_long_url(short_code)
        
        if not long_url:
            return {
                'statusCode': 404,
                'headers': headers,
                'body': json.dumps({'error': 'Short code not found'})
            }
        
        return {
            'statusCode': 301,
            'headers': {
                'Location': long_url,
                'Access-Control-Allow-Origin': '*'
            },
            'body': ''
        }
    
    # Root endpoint
    elif http_method == 'GET' and path == '/':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'message': 'URL Shortener API',
                'endpoints': {
                    'shorten': 'POST /shorten',
                    'redirect': 'GET /{shortCode}'
                }
            })
        }
    
    else:
        return {
            'statusCode': 404,
            'headers': headers,
            'body': json.dumps({'error': 'Endpoint not found'})
        }
