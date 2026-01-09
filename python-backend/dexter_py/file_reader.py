"""Tool for reading and analyzing files."""

from typing import Optional, Dict, Any, List
import os
import json
import re
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class FileReaderTool:
    """Tool to read and analyze files from the local filesystem."""

    def __init__(self):
        self.description = (
            "Read and analyze .txt and .csv files from allowed directories. "
            "Provides structured analysis including schema inference, summary statistics, "
            "anomaly detection, and time series analysis when applicable. "
            "Requires absolute paths within allowed directories."
        )
        # Define allowed directory prefixes for security
        self.allowed_dirs = self._get_allowed_directories()

    def _get_allowed_directories(self) -> List[str]:
        """Get list of allowed directory prefixes."""
        home = os.path.expanduser("~")
        allowed = [
            home,
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            "C:\\Users",  # Allow user directories
        ]
        # Add drive letters for Windows
        import string
        for letter in string.ascii_uppercase:
            allowed.append(f"{letter}:\\")
        return allowed

    def _is_path_safe(self, file_path: str) -> bool:
        """Check if the file path is within allowed directories."""
        if not file_path or not os.path.isabs(file_path):
            return False
        
        # Normalize path
        file_path = os.path.normpath(file_path)
        
        # Check against allowed directories
        for allowed_dir in self.allowed_dirs:
            if file_path.startswith(os.path.normpath(allowed_dir)):
                return True
        
        # Additional checks
        dangerous_patterns = [
            "..",  # Directory traversal
            "\\\\",  # UNC paths
            "/etc", "/bin", "/usr", "/var", "/sys", "/proc",  # Unix system dirs
            "C:\\Windows", "C:\\Program Files", "C:\\System32",  # Windows system dirs
        ]
        
        for pattern in dangerous_patterns:
            if pattern in file_path:
                return False
        
        return False  # Default deny

    def analyze_file(self, file_path: str, analysis_type: Optional[str] = None) -> Dict[str, Any]:
        """Analyze a file and return structured results.
        
        Args:
            file_path: Absolute path to the file
            analysis_type: Type of analysis ('basic', 'detailed', 'anomalies', 'timeseries')
        
        Returns:
            Dict with analysis results
        """
        try:
            if not self._is_path_safe(file_path):
                return {"error": "Path not allowed or unsafe", "path": file_path}
            
            if not os.path.exists(file_path):
                return {"error": "File does not exist", "path": file_path}
            
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.csv':
                return self._analyze_csv(file_path, analysis_type)
            elif file_ext == '.txt':
                return self._analyze_txt(file_path, analysis_type)
            else:
                return {"error": "Unsupported file type. Only .csv and .txt supported", "extension": file_ext}
                
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}", "path": file_path}

    def _analyze_csv(self, file_path: str, analysis_type: Optional[str]) -> Dict[str, Any]:
        """Analyze CSV file with pandas."""
        if not PANDAS_AVAILABLE:
            return {"error": "pandas not available for CSV analysis"}
        
        try:
            df = pd.read_csv(file_path)
            result = {
                "file_type": "csv",
                "path": file_path,
                "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
                "columns": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            }
            
            # Basic stats
            if analysis_type in [None, 'basic', 'detailed']:
                numeric_cols = df.select_dtypes(include=['number']).columns
                if len(numeric_cols) > 0:
                    result["numeric_stats"] = df[numeric_cols].describe().to_dict()
                
                # Missing values
                missing = df.isnull().sum()
                result["missing_values"] = missing[missing > 0].to_dict()
            
            # Anomaly detection
            if analysis_type in ['detailed', 'anomalies']:
                result["anomalies"] = self._detect_anomalies(df)
            
            # Time series analysis
            if analysis_type in ['detailed', 'timeseries']:
                result["timeseries_analysis"] = self._analyze_timeseries(df)
            
            # Sample data
            result["sample"] = df.head(5).to_dict('records')
            
            return result
            
        except Exception as e:
            return {"error": f"CSV analysis failed: {str(e)}"}

    def _analyze_txt(self, file_path: str, analysis_type: Optional[str]) -> Dict[str, Any]:
        """Analyze text file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            result = {
                "file_type": "txt",
                "path": file_path,
                "size": len(content),
                "lines": len(content.split('\n')),
            }
            
            # Try to detect structure
            if self._is_tabular_txt(content):
                # Try to parse as CSV-like
                try:
                    from io import StringIO
                    df = pd.read_csv(StringIO(content), sep=None, engine='python')
                    result["parsed_as_table"] = True
                    result["table_shape"] = {"rows": int(df.shape[0]), "columns": int(df.shape[1])}
                    result["table_columns"] = list(df.columns)
                    result["table_sample"] = df.head(3).to_dict('records')
                except:
                    result["parsed_as_table"] = False
            else:
                result["parsed_as_table"] = False
            
            # Content analysis
            result["word_count"] = len(content.split())
            result["character_count"] = len(content)
            
            # Detect if it's a log file
            if self._is_log_file(content):
                result["content_type"] = "log"
                result["log_entries"] = len([line for line in content.split('\n') if line.strip()])
            else:
                result["content_type"] = "text"
            
            # Sample content
            lines = content.split('\n')[:10]
            result["sample_content"] = '\n'.join(lines)
            
            return result
            
        except Exception as e:
            return {"error": f"TXT analysis failed: {str(e)}"}

    def _is_tabular_txt(self, content: str) -> bool:
        """Check if text content looks tabular."""
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if len(lines) < 2:
            return False
        
        # Check if first few lines have similar number of separators
        separators = [',', '\t', ';', '|']
        for sep in separators:
            counts = [line.count(sep) for line in lines[:5]]
            if len(set(counts)) == 1 and counts[0] > 0:
                return True
        return False

    def _is_log_file(self, content: str) -> bool:
        """Check if content looks like a log file."""
        lines = content.split('\n')[:10]
        log_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # Date
            r'\d{2}:\d{2}:\d{2}',  # Time
            r'\[.*\]',  # Brackets
            r'ERROR|INFO|WARN|DEBUG',  # Log levels
        ]
        log_score = 0
        for line in lines:
            for pattern in log_patterns:
                if re.search(pattern, line):
                    log_score += 1
        return log_score > len(lines) * 0.3

    def _detect_anomalies(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Basic anomaly detection."""
        anomalies = {}
        numeric_cols = df.select_dtypes(include=['number']).columns
        
        for col in numeric_cols:
            series = df[col].dropna()
            if len(series) > 10:
                mean = series.mean()
                std = series.std()
                outliers = series[(series - mean).abs() > 3 * std]
                if len(outliers) > 0:
                    anomalies[col] = {
                        "outlier_count": len(outliers),
                        "outlier_values": outliers.tolist()[:5],  # First 5
                        "threshold": 3 * std
                    }
        
        return anomalies

    def _analyze_timeseries(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Basic time series analysis."""
        analysis = {}
        
        # Try to detect date columns
        date_cols = []
        for col in df.columns:
            try:
                pd.to_datetime(df[col].dropna().head())
                date_cols.append(col)
            except:
                pass
        
        if date_cols:
            analysis["potential_date_columns"] = date_cols
            
            # Basic temporal analysis
            for col in date_cols:
                try:
                    dates = pd.to_datetime(df[col].dropna())
                    analysis[f"{col}_range"] = {
                        "start": str(dates.min()),
                        "end": str(dates.max()),
                        "span_days": (dates.max() - dates.min()).days
                    }
                except:
                    pass
        
        return analysis


# Instance for registry
file_reader_tool = FileReaderTool()