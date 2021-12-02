import json
import urllib.parse
import boto3
from email.parser import BytesParser
from email import policy
import email

# from sagemaker.mxnet.model import MXNetPredictor
from utils import one_hot_encode
from utils import vectorize_sequences

vocabulary_length = 9013
AWS_REGION = "us-west-2"
CHARSET = "UTF-8"
endpoint_name = "sms-spam-classifier-mxnet-2021-12-02-05-57-55-675"

s3 = boto3.client('s3')
runtime = boto3.Session().client(service_name='sagemaker-runtime', region_name='us-west-2')
ses_client = boto3.client('ses', region_name=AWS_REGION)


def construct_reply_message(email_receive_date, subject, classification_label, probability_score, email_body):
    message_statement_one = "We received your email sent at {} with the subject {}.".format(email_receive_date, subject)
    email_body_len = len(email_body)
    if email_body_len > 240:
        email_body = email_body[:240]

    message_statement_two = "Here is a {} character sample of the email body:".format(len(email_body))
    inference_statement = "The email was categorized as {} with a {}% confidence.".format(classification_label,
                                                                                          round(probability_score * 100,
                                                                                                4))

    final_message = message_statement_one + "\n" + message_statement_two + "\n" + email_body + "\n" + inference_statement
    return final_message


def lambda_handler(event, context):
    # print("Received event: " + json.dumps(event, indent=2))
    # print("EVENT: {}".format(event))
    bucket = event['Records'][0]['s3']
    key = bucket['object']['key']
    bucket_name = bucket['bucket']['name']
    # Get the object from the event and show its content type
    key = urllib.parse.unquote_plus(key, encoding='utf-8')
    try:
        response = s3.get_object(Bucket=bucket_name, Key=key)
        response_body = response['Body'].read()
        email_raw_msg = BytesParser(policy=policy.SMTP).parsebytes(response_body)
        # print("email_raw_msg: {}".format(email_raw_msg))

        # Getting Message Date
        email_datetime = email_raw_msg['Date']

        # Getting Email Subject
        email_subject = email_raw_msg['Subject']

        # From Email:
        from_email = email_raw_msg['From']

        # From Email:
        to_email = email_raw_msg['To']

        # Getting Message Body
        email_body = email_raw_msg.get_body(preferencelist=('plain'))
        email_body = ''.join(email_body.get_content().splitlines(keepends=True))
        email_body = '' if email_body == None else email_body

        # Preditct Spam:
        input_mail = [email_body.strip()]
        one_hot_test_messages = one_hot_encode(input_mail, vocabulary_length)
        encoded_test_messages = vectorize_sequences(one_hot_test_messages, vocabulary_length)
        data = json.dumps(encoded_test_messages.tolist())

        response = runtime.invoke_endpoint(EndpointName=endpoint_name, ContentType='application/json', Body=data)
        raw_sagemaker_response = response['Body'].read().decode()
        raw_sagemaker_response = json.loads(raw_sagemaker_response)

        label = raw_sagemaker_response['predicted_label'][0][0]
        predicted_probability = raw_sagemaker_response['predicted_probability'][0][0]

        if int(label) == 1:
            classification_label = "SPAM"
        else:
            classification_label = "HAM"

        reply_message = construct_reply_message(email_datetime, email_subject, classification_label,
                                                predicted_probability, email_body)
        reply_message_subject = "Spam Detection Report"

        # Send Email:
        response = ses_client.send_email(
            Destination={
                'ToAddresses': [
                    str(from_email),
                ],
            },
            Message={
                'Body': {
                    'Text': {
                        'Charset': CHARSET,
                        'Data': reply_message,
                    },
                },
                'Subject': {
                    'Charset': CHARSET,
                    'Data': reply_message_subject,
                },
            },
            Source=str(to_email),
        )
        return reply_message

    except Exception as e:
        print('Faced Error '.format(str(e)))
        raise e
