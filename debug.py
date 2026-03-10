from google.cloud import pubsub_v1

# Replace with your actual project/topic
project_id = "llm-app-488813"
topic_id = "topic_doi"

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(project_id, topic_id)

print(f"Attempting to connect to: {topic_path}")

try:
    # A simple "get_topic" check (this is an API call)
    topic = publisher.get_topic(request={"topic": topic_path})
    print("Successfully connected to topic!")
except Exception as e:
    print(f"FAILED TO CONNECT: {e}")