# CIS7000-Project-TaskGenie

## Set up Environment Variables

### Temporary Setup (Current Session Only)

1. Open your terminal or command prompt.

2. Set your environment variables using placeholder values:

   ```bash
   # OpenAI
   export OPENAI_API_KEY="xxx"

   # Azure
   export AZURE_OPENAI_API_KEY="xxx"
   export AZURE_OPENAI_ENDPOINT="xxx"
 
   # MongoDB
   export MONGODB_URI="xxx"
   ```

### Persistent Storage in ~/.zshrc

For a more persistent setup using `~/.zshrc`:

1. Open your `~/.zshrc` file in a text editor:

   ```bash
   nano ~/.zshrc
   ```

2. Add the following lines at the end of the file:

   ```bash
   # OpenAI
   export OPENAI_API_KEY="xxx"

   # Azure
   export AZURE_OPENAI_API_KEY="xxx"
   export AZURE_OPENAI_ENDPOINT="xxx"
 
   # MongoDB
   export MONGODB_URI="xxx"
   ```

3. Save the file and exit the editor (in nano, press Ctrl+X, then Y, then Enter).

4. Reload your `~/.zshrc` file:

   ```bash
   source ~/.zshrc
   ```
