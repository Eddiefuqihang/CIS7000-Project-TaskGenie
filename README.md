# TaskGenie - AI-Powered Task Management System

## Overview
TaskGenie is an intelligent task management system that leverages OpenAI and Azure's AI capabilities to help users organize, track, and optimize their tasks efficiently.

## Features
- AI-powered task analysis and optimization
- CRUD operations for task management
- Integration with OpenAI and Azure OpenAI services
- MongoDB database storage
- Jupyter notebook for evaluation and testing

## Prerequisites
- Python 3.10 or higher
- MongoDB API access
- OpenAI API access / Azure OpenAI API access

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Eddiefuqihang/CIS7000-Project-TaskGenie.git
cd CIS7000-Project-TaskGenie
```

## Environment Setup

### Temporary Setup (Current Session Only)
1. Open your terminal or command prompt
2. Set your environment variables:
```bash
# OpenAI
export OPENAI_API_KEY="your_openai_api_key"

# Azure
export AZURE_OPENAI_API_KEY="your_azure_openai_api_key"
export AZURE_OPENAI_ENDPOINT="your_azure_endpoint"

# MongoDB
export MONGODB_URI="your_mongodb_connection_string"
```

### Persistent Storage (Using ~/.zshrc)
1. Open your `~/.zshrc` file:
```bash
nano ~/.zshrc
```

2. Add the following environment variables:
```bash
# OpenAI
export OPENAI_API_KEY="your_openai_api_key"

# Azure
export AZURE_OPENAI_API_KEY="your_azure_openai_api_key"
export AZURE_OPENAI_ENDPOINT="your_azure_endpoint"

# MongoDB
export MONGODB_URI="your_mongodb_connection_string"
```

3. Save and reload the configuration:
```bash
source ~/.zshrc
```

### Conda Environment Setup
1. Create a new Conda environment:
```bash
conda create -n taskgenie python=3.10.11
```

2. Activate the environment:
```bash
conda activate taskgenie
```

3. Install required packages:
```bash
conda install pip
pip install -r requirements.txt
```

4. If you need specific packages from Conda:
```bash
conda install numpy pandas jupyter
```

5. To deactivate the environment when you're done:
```bash
conda deactivate
```

Note: Make sure to activate the Conda environment (`conda activate taskgenie`) every time you work on the project.

## Project Structure
```
CIS7000-Project-TaskGenie/
├── templates/
│   └── index.html                  # Flask frontend
├── app.py                          # Flask application
├── taskgenie.py                    # Core TaskGenie functionality
├── requirements.txt                # Project dependencies
├── CRUD Evaluation.ipynb           # Jupyter notebook for testing
├── TaskGenie CRUD Evaluation.xlsx  # Evaluation data
├── .gitignore
└── LICENSE
```

## Usage

1. Start the Flask application:
```bash
python app.py
```

2. Access the web interface at `http://localhost:5000`

3. For evaluation and testing, use the Jupyter notebook:
```bash
jupyter notebook "CRUD Evaluation.ipynb"
```

## API Reference

The system provides the following core functionalities through `taskgenie.py`:
- Task Creation
- Task Retrieval
- Task Updates
- Task Deletion
- AI-powered Task Analysis

Detailed API documentation can be found in the code comments.

## Evaluation

The project includes evaluation materials:
- `CRUD Evaluation.ipynb`: Jupyter notebook containing test cases and performance metrics
- `TaskGenie CRUD Evaluation.xlsx`: Detailed evaluation data and results

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
