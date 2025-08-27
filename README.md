# Temp Deleter

Temp Deleter is a tool developed to clean unnecessary files from the system at specified intervals. Through the
application, you can create tasks, set different time intervals for each task, and link different folders such as 
- Local Temp
- Temp
- Prefetch
- Recents

to different times.

## How Does It Work?

The application monitors the defined tasks while running. When the time comes for a task, unnecessary files in the
relevant folders are deleted, and the results are reported to the user.

## Installation

1. Create a virtual environment using a terminal or IDE:

```bash
python -m venv .venv
```

2. Activate the created virtual environment:

```bash
.venv\Scripts\Activate
```

3. While the virtual environment is active, install the required packages:

```bash
pip install -r ./requirements.txt
```

4. After completing the installation, start the application:

```bash
python app.py
```

## Building

1. While the virtual environment is active, install the PyInstaller package:

```bash
pip install pyinstaller
```

2. Start the build process using the prepared `.spec` file:

```bash
pyinstaller TempDeleter.spec
```

3. Once the build is complete, a folder named `TempDeleter` will be created inside the `dist` directory.

## Note

Since this application performs file deletion operations, some antivirus software may detect it as a virus. However, the
application is digitally signed and can be used safely. You can check the validity of the digital signature before using the
application.