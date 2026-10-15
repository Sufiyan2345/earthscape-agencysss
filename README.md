# EarthScape Climate System

A comprehensive web-based climate analysis and monitoring platform built with Flask. This system provides tools for data ingestion, storage, processing, machine learning, real-time monitoring, and interactive visualization of climate data.

## Features

- **User Authentication & Authorization**: Role-based access control (Admin, Analyst)
- **Data Ingestion**: Support for satellite, weather station, and sensor data
- **HDFS Storage**: Simulated Hadoop Distributed File System for scalable storage
- **MapReduce Processing**: Parallel processing of climate data with job management
- **Machine Learning**: Predictive models for temperature, rainfall, flood risk, heatwave, air quality, and climate trends
- **Real-time Monitoring**: Live data streaming and anomaly detection
- **Interactive Dashboards**: Charts and visualizations using Chart.js
- **Alerts & Notifications**: Automated alerts based on configurable thresholds
- **Report Generation**: Climate summary, anomaly, trend, and prediction reports
- **Feedback System**: Support and feedback mechanism for users

### Real Hadoop / Ambari deployment

The application uses MongoDB for fast dashboard metadata and WebHDFS/YARN for
large climate files and real MapReduce jobs. On a computer with the institute
cluster available, configure these variables before starting Flask:

```powershell
$env:HDFS_USE_REAL = "true"
$env:HDFS_NAMENODE = "http://namenode-host:9870"
$env:HDFS_USER = "climateservice"
$env:HADOOP_RESOURCE_MANAGER = "http://resourcemanager-host:8088"
$env:HADOOP_HOME = "C:\hadoop"
$env:HADOOP_STREAMING_JAR = (Get-ChildItem "C:\hadoop\share\hadoop\tools\lib\hadoop-streaming-*.jar" | Select-Object -First 1).FullName
python app.py
```

Use the actual NameNode, ResourceManager, Hadoop home, and streaming JAR paths
provided by the institute administrator. Verify the result at
`/admin/system-status`: it should report `Real HDFS (WebHDFS)` and
`Real Hadoop/YARN`. Uploaded files are written under `/climate/<category>/`.
Analyst MapReduce jobs read HDFS input and write results under
`/climate/results/`, where they are visible to HDFS/Ambari file views and as
YARN applications. If these variables are absent, the application keeps its
local development simulation.

## Tech Stack

- **Backend**: Python 3, Flask
- **Database**: SQLite (simulating Hadoop ecosystem)
- **Frontend**: HTML5, CSS3, JavaScript, Chart.js
- **Styling**: Custom teal/white professional theme
- **ML**: NumPy, scikit-learn (optional), pickle

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd EarthScape-Climate-System
```

2. Create a virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

Optional NetCDF, HDF5, and GeoTIFF dataset parsers and the Kafka backend (not
included in the size-constrained Vercel deployment) can be installed locally
with:
```bash
pip install -r requirements-optional.txt
```

4. Train ML models (optional):
```bash
python ml_models/train_model.py
```

5. Run the application:
```bash
python app.py
```

6. Open browser and navigate to `http://localhost:5000`

## Deploying to Vercel

The root `index.py` exposes the Flask application to Vercel. Static assets are
published from `public/static` and served by Vercel's CDN rather than included
in the Flask function bundle. Configure these production environment variables
in the Vercel project before deployment:

- `MONGO_URI` — MongoDB connection string for the production database
- `SECRET_KEY` — a unique, randomly generated Flask session key
- `SESSION_COOKIE_SECURE` — set to `true`
- `INITIAL_ADMIN_PASSWORD`, `INITIAL_ANALYST_PASSWORD`, and
  `INITIAL_ANALYSIS_USER_PASSWORD` — unique passwords used when seeding an
  empty database. Set them before the first deployment; default demo passwords
  are for local development only.

The model scheduler and Kafka consumer are disabled on Vercel. NetCDF, HDF5,
and GeoTIFF dataset parsers are optional dependencies and are not installed in
the Vercel build to stay below the function bundle limit; CSV, JSON, Excel, and
other core app features remain available. Runtime uploads, datasets, and
generated reports use `/tmp`, which is temporary serverless storage and is not
shared between function instances. Use external object storage for files that
must persist. Large uploads may also exceed Vercel's request limits.
Profile photos and banners are stored in MongoDB so profile image uploads work
with Vercel's read-only function filesystem.

### AI Climate Agent

## Default Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin | admin | admin123 (local development only) |
| Analyst | analyst | analyst123 (local development only) |

## Project Structure

```
EarthScape-Climate-System/
├── app.py              # Main Flask application
├── config.py           # Configuration settings
├── requirements.txt    # Python dependencies
├── admin/              # Admin blueprint routes
├── analyst/            # Analyst blueprint routes
├── auth/               # Authentication (login, register, logout)
├── public/             # Public pages
├── templates/          # Jinja2 HTML templates
├── models/             # Data models
├── utils/              # Utility modules (HDFS, MapReduce)
├── hadoop/             # Hadoop scripts (HDFS, MapReduce)
├── ml_models/          # Machine learning models
├── static/             # CSS, JS, images
├── datasets/           # Dataset storage
├── uploads/            # User uploads
├── reports/            # Generated reports
└── logs/               # Application logs
```

## API Endpoints

- `/` - Home page
- `/about` - About page
- `/services` - Services page
- `/climate-insights` - Climate insights
- `/contact` - Contact form
- `/auth/login` - User login
- `/auth/register` - User registration
- `/admin/*` - Admin dashboard and management
- `/analyst/*` - Analyst dashboard and tools

## License

MIT License
