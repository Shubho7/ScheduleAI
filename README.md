# ScheduleAI
ScheduleAI is an intelligent AI voice assistant designed to automate your scheduling operations. It provides a conversational interface for creating, editing, viewing, and deleting calendar events through both text and voice commands.

![ScheduleAI Interface](./assests/Screenshot%202025-07-01%20173316.png)

### Objective 🚀
The primary goal of ScheduleAI is to simplify calendar management. By integrating with Google Calendar, ScheduleAI aims to provide users with a seamless and intuitive way to:

- **Create new events -** Quickly add any appointments, meetings or any event to your calendar

- **List events -** Get a clear overview of your upcoming appointments

- **Edit existing events -** Modify event details such as time, date, and description with ease

- **Delete events -** Remove unwanted or outdated entries from your schedule

- **Find free time  -** Identify available slots in your schedule based on your existing commitments

### How It Works ⚙️ 

ScheduleAI leverages Google's Agent Development Kit (ADK) to create an intelligent AI Event Manager agent that can:

- **Understand natural language requests -** The AI engine interprets your scheduling intent and extracts key information from your commands

- **Execute calendar operations -** The agent translates user requests into specific Google Calendar API calls allowing it to create, edit, delete, or retrieve event information

- **Real-time Communication -** For voice interactions, ScheduleAI utilizes WebSockets to maintain a real-time, bidirectional audio stream, ensuring a smooth and responsive conversational experience

- **Manage scheduling conflicts -** The system can identify conflicts and suggest alternatives

### Architecture 🔎

- **FastAPI Backend -** Handles WebSocket connections and integrates with Google ADK using asynchronous request handling. Implements communication channels with `agent_to_client_messaging` and `client_to_agent_messaging` functions to process events and requests.

- **AI -** Uses Google ADK with `gemini-live-2.5-flash-preview` live model to create the `event_manager` AI agent

- **WebSocket Communication -** Enables real-time communication for both text and voice interactions. The system maintains persistent connections through the `/ws/{session_id}` endpoint with separate async tasks for sending and receiving messages.

- **Audio Processing -** Implements Web Audio API's AudioWorklet for high-performance, low-latency audio processing. It captures audio using `PCMProcessor` in the audio-recorder worklet

### Project Structure 📂

```
├── app/                                    # Main application directory
│   ├── event_manager/                      # AI agent implementation
│   │   ├── agent.py                        # Agent definition and configuration
│   │   └── tools/                          # Calendar operation tools
│   │       ├── create_event.py             # Tool for creating events
│   │       ├── delete_event.py             # Tool for deleting events
│   │       ├── edit_event.py               # Tool for editing events
│   │       ├── find_free_time.py           # Tool for finding free time slots
│   │       ├── list_event.py               # Tool for listing events
│   │       └── utils.py                    # Utility functions
│   ├── main.py                             # FastAPI application entry point
│   └── static/                             # Frontend
│       ├── index.html                      # Web interface
│       └── js/                             # JavaScript modules
│           ├── app.js                      # Main application logic
│           ├── audio-player.js             # Audio playback handling
│           ├── audio-recorder.js           # Audio recording handling
            ├── pcm-player-processor.js     # AudioWorklet processors
│           └── pcm-recorder-processor.js   # AudioWorklet processors
├── auth.py                                 # Google OAuth authentication
├── pyproject.toml                          # Project dependencies
└── requirements.txt                        # Project dependencies
```